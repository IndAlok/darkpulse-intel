from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from darkpulse.api.deps import SettingsDep

Role = Literal["viewer", "analyst", "administrator"]
_ROLE_ORDER: dict[Role, int] = {"viewer": 0, "analyst": 1, "administrator": 2}
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    role: Role


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
            principals[token] = Principal(subject=subject, role=role)
        return principals
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Invalid server auth configuration") from exc


async def current_principal(
    request: Request,
    settings: SettingsDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if not settings.auth.enabled:
        return Principal(
            subject=request.headers.get("X-DarkPulse-Actor", "local-developer"),
            role="administrator",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required"
        )
    principals = _configured_principals(settings)
    for token, principal in principals.items():
        if secrets.compare_digest(token, credentials.credentials):
            return principal
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")


def websocket_principal(token: str | None, settings: SettingsDep) -> Principal | None:
    if not settings.auth.enabled:
        return Principal(subject="local-developer", role="administrator")
    if not token:
        return None
    for configured_token, principal in _configured_principals(settings).items():
        if secrets.compare_digest(configured_token, token):
            return principal
    return None


def require_role(minimum: Role) -> Callable[..., Any]:
    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if _ROLE_ORDER[principal.role] < _ROLE_ORDER[minimum]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return principal

    return dependency


ViewerDep = Annotated[Principal, Depends(require_role("viewer"))]
AnalystDep = Annotated[Principal, Depends(require_role("analyst"))]
AdminDep = Annotated[Principal, Depends(require_role("administrator"))]
