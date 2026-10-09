from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request, status

_WINDOW_SECONDS = 60
_WRITE_LIMIT = 60
_MAX_KEYS = 10_000
_LIMITED_SUFFIXES = ("/export", "/evidence/verify", "/graph", "/search")
_hits: dict[str, deque[float]] = defaultdict(deque)
_redis: Any = None
_redis_disabled = False


def reset_rate_limits() -> None:
    global _redis, _redis_disabled
    _hits.clear()
    _redis = None
    _redis_disabled = False


def _identity(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
        if token:
            return hashlib.sha256(token.encode()).hexdigest()[:32]
    principal = getattr(request.state, "principal", None)
    subject = getattr(principal, "subject", None)
    if isinstance(subject, str) and subject:
        return subject
    return request.client.host if request.client else "unknown"


def _limited(request: Request) -> bool:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    path = request.url.path.rstrip("/")
    return path.endswith(_LIMITED_SUFFIXES)


async def _charge_redis(redis: Any, key: str) -> bool:
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, _WINDOW_SECONDS)
    else:
        ttl = await redis.ttl(key)
        if ttl is not None and int(ttl) < 0:
            await redis.expire(key, _WINDOW_SECONDS)
    return count <= _WRITE_LIMIT


async def _shared_redis(request: Request) -> Any:
    global _redis, _redis_disabled
    if _redis_disabled:
        return None
    if _redis is not None:
        return _redis
    settings = getattr(request.app.state, "settings", None)
    url = getattr(getattr(settings, "redis", None), "url", None)
    if not url:
        _redis_disabled = True
        return None
    from redis.asyncio import Redis

    client = Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=0.2, socket_timeout=0.2
    )
    try:
        await client.ping()
    except Exception:
        _redis_disabled = True
        await client.aclose()
        return None
    _redis = client
    return client


def _charge_memory(key: str) -> bool:
    now = time.monotonic()
    if len(_hits) > _MAX_KEYS:
        stale = [
            item
            for item, hits in _hits.items()
            if not hits or now - hits[-1] > _WINDOW_SECONDS
        ]
        for item in stale:
            del _hits[item]
    bucket = _hits[key]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if not bucket and key in _hits:
        del _hits[key]
        bucket = _hits[key]
    if len(bucket) >= _WRITE_LIMIT:
        return False
    bucket.append(now)
    return True


async def enforce_write_rate_limit(request: Request) -> None:
    if not _limited(request):
        return
    key = f"{_identity(request)}:{request.url.path}"
    allowed = True
    redis = await _shared_redis(request)
    if redis is not None:
        try:
            allowed = await _charge_redis(redis, key)
        except HTTPException:
            raise
        except Exception:
            allowed = _charge_memory(key)
    else:
        allowed = _charge_memory(key)
    if allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests; retry shortly",
        headers={"Retry-After": str(_WINDOW_SECONDS)},
    )
