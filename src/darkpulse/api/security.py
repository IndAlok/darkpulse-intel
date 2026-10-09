from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from darkpulse.api.deps import SettingsDep

logger = structlog.get_logger(__name__)

Role = Literal["viewer", "analyst", "administrator"]
_ROLE_ORDER: dict[Role, int] = {"viewer": 0, "analyst": 1, "administrator": 2}
_bearer = HTTPBearer(auto_error=False)
_sessions: dict[str, tuple[Principal, float, str]] = {}
_tickets: dict[str, tuple[Principal, float]] = {}
_SESSION_TTL = 8 * 60 * 60
_TICKET_TTL = 60
_SESSION_PREFIX = "dp:session:"
_TICKET_PREFIX = "dp:ticket:"
_redis: Any = None
_redis_url: str | None = None
_redis_disabled = False
_USE_MEMORY = object()
# "testclient" is the peer Starlette's in-process TestClient reports. It is never a network host.
_LOCAL_PEERS = frozenset({"127.0.0.1", "::1", "testclient"})


def _sweep(store: dict[str, Any], now: float) -> None:
    for key in [key for key, item in store.items() if item[1] < now]:
        store.pop(key, None)


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    role: Role


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def bind_session_store(url: str | None) -> None:
    global _redis_url, _redis
    if _redis_disabled:
        return
    _redis_url = url or None
    _redis = None


def close_session_store() -> None:
    global _redis
    client = _redis
    _redis = None
    if client is not None:
        client.close()


def _client() -> Any:
    global _redis, _redis_disabled
    if _redis_disabled:
        return None
    if _redis is not None:
        return _redis
    if not _redis_url:
        return None
    from redis import Redis

    client = Redis.from_url(
        _redis_url,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    try:
        client.ping()
    except Exception:
        logger.warning("session.redis_unavailable")
        _redis_disabled = True
        client.close()
        return None
    _redis = client
    return client


def _encode_session(principal: Principal, expires: float, source: str) -> str:
    return json.dumps(
        {
            "subject": principal.subject,
            "role": principal.role,
            "exp": expires,
            "source": source,
        }
    )


def _decode_session(raw: str) -> tuple[Principal, float, str] | None:
    try:
        payload = json.loads(raw)
        role = payload["role"]
        subject = payload["subject"]
        if role not in _ROLE_ORDER or not isinstance(subject, str) or not subject:
            return None
        return Principal(subject=subject, role=role), float(payload["exp"]), str(payload["source"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _encode_ticket(principal: Principal, expires: float) -> str:
    return json.dumps(
        {"subject": principal.subject, "role": principal.role, "exp": expires}
    )


def _decode_ticket(raw: str) -> tuple[Principal, float] | None:
    try:
        payload = json.loads(raw)
        role = payload["role"]
        subject = payload["subject"]
        if role not in _ROLE_ORDER or not isinstance(subject, str) or not subject:
            return None
        return Principal(subject=subject, role=role), float(payload["exp"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _write_shared(key: str, payload: str, ttl: int) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.setex(key, ttl, payload)
    except Exception:
        logger.warning("session.redis_write_failed")


def _delete_shared(key: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        logger.warning("session.redis_delete_failed")


def mint_session(principal: Principal, source_token: str) -> str:
    now = time.time()
    _sweep(_sessions, now)
    raw = secrets.token_urlsafe(32)
    expires = now + _SESSION_TTL
    source = _digest(source_token)
    key = _digest(raw)
    _sessions[key] = (principal, expires, source)
    _write_shared(
        f"{_SESSION_PREFIX}{key}",
        _encode_session(principal, expires, source),
        _SESSION_TTL,
    )
    return raw


def revoke_session(raw: str) -> None:
    key = _digest(raw)
    _sessions.pop(key, None)
    _delete_shared(f"{_SESSION_PREFIX}{key}")


def _shared_session(key: str) -> tuple[Principal, float, str] | None | object:
    client = _client()
    if client is None:
        return _USE_MEMORY
    try:
        stored = client.get(f"{_SESSION_PREFIX}{key}")
    except Exception:
        logger.warning("session.redis_read_failed")
        return _USE_MEMORY
    if not stored:
        _sessions.pop(key, None)
        return None
    loaded = _decode_session(stored)
    if loaded is None:
        return None
    _sessions[key] = loaded
    return loaded


def principal_from_session(raw: str, settings: SettingsDep) -> Principal | None:
    key = _digest(raw)
    shared = _shared_session(key)
    item = _sessions.get(key) if shared is _USE_MEMORY else shared
    if item is None:
        return None
    if not isinstance(item, tuple) or len(item) != 3:
        return None
    principal, expires, source = item
    if not isinstance(principal, Principal):
        return None
    configured = _configured_principals(settings)
    current = next(
        (value for token, value in configured.items() if _digest(token) == source), None
    )
    if time.time() > expires or current != principal:
        _sessions.pop(key, None)
        _delete_shared(f"{_SESSION_PREFIX}{key}")
        return None
    return principal


def mint_ticket(principal: Principal) -> str:
    now = time.time()
    _sweep(_tickets, now)
    raw = secrets.token_urlsafe(24)
    expires = now + _TICKET_TTL
    key = _digest(raw)
    _tickets[key] = (principal, expires)
    _write_shared(f"{_TICKET_PREFIX}{key}", _encode_ticket(principal, expires), _TICKET_TTL)
    return raw


def consume_ticket(raw: str) -> Principal | None:
    key = _digest(raw)
    client = _client()
    if client is None:
        item = _tickets.pop(key, None)
    else:
        try:
            stored = client.getdel(f"{_TICKET_PREFIX}{key}")
        except Exception:
            logger.warning("session.redis_ticket_failed")
            item = _tickets.pop(key, None)
        else:
            _tickets.pop(key, None)
            item = _decode_ticket(stored) if stored else None
    if item is None:
        return None
    principal, expires = item
    if time.time() > expires:
        return None
    return principal


class TokenExpiredError(Exception):
    def __init__(self, token: str) -> None:
        self.token = token


def _configured_principals(settings: SettingsDep) -> dict[str, Principal]:
    secret = settings.auth.tokens_json
    if not secret:
        return {}
    try:
        raw = json.loads(secret.get_secret_value())
        if not isinstance(raw, dict):
            raise ValueError("token configuration must be an object")
        principals: dict[str, Principal] = {}
        for token, value in raw.items():
            if not isinstance(token, str) or not isinstance(value, dict):
                raise ValueError("invalid token configuration")
            role = value.get("role")
            subject = value.get("subject")
            if role not in _ROLE_ORDER or not isinstance(subject, str) or not subject:
                raise ValueError("every token needs a subject and valid role")
            expires_at = value.get("expires_at")
            if expires_at is not None:
                if isinstance(expires_at, str):
                    from datetime import datetime

                    expires_at = datetime.fromisoformat(expires_at).timestamp()
                elif isinstance(expires_at, (int, float)):
                    expires_at = float(expires_at)
                else:
                    raise ValueError("expires_at must be an ISO string or epoch seconds")
                if expires_at < time.time():
                    raise TokenExpiredError(token)
            principals[token] = Principal(subject=subject, role=role)
        return principals
    except TokenExpiredError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Invalid server auth configuration") from exc


async def current_principal(
    request: Request,
    settings: SettingsDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if not settings.auth.enabled:
        principal = open_mode_principal(settings, request.client.host if request.client else None)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
            )
        request.state.principal = principal
        return principal
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
        )
    session = principal_from_session(credentials.credentials, settings)
    if session is not None:
        request.state.principal = session
        return session
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")


def open_mode_principal(settings: SettingsDep, peer: str | None) -> Principal | None:
    if not settings.auth.local_open_mode or peer not in _LOCAL_PEERS:
        return None
    return Principal(subject="local-developer", role="administrator")


def configured_principal(token: str | None, settings: SettingsDep) -> Principal | None:
    if not token:
        return None
    try:
        principals = _configured_principals(settings)
    except TokenExpiredError as exc:
        if secrets.compare_digest(exc.token, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token expired"
            ) from exc
        principals = _configured_principals(_expiry_stripped(settings))
    for configured_token, principal in principals.items():
        if secrets.compare_digest(configured_token, token):
            return principal
    return None


def _expiry_stripped(settings: SettingsDep) -> SettingsDep:
    import copy

    from pydantic import SecretStr

    clone = copy.copy(settings)
    clone.auth = copy.copy(settings.auth)
    secret = settings.auth.tokens_json
    if secret is None:
        return settings
    raw = json.loads(secret.get_secret_value())
    for value in raw.values():
        value.pop("expires_at", None)
    clone.auth.tokens_json = SecretStr(json.dumps(raw))
    return clone


def require_role(minimum: Role) -> Callable[..., Any]:
    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if _ROLE_ORDER[principal.role] < _ROLE_ORDER[minimum]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return principal

    return dependency


ViewerDep = Annotated[Principal, Depends(require_role("viewer"))]
AnalystDep = Annotated[Principal, Depends(require_role("analyst"))]
AdminDep = Annotated[Principal, Depends(require_role("administrator"))]
