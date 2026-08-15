from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_WINDOW_SECONDS = 60
_WRITE_LIMIT = 60
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    _hits.clear()


async def enforce_write_rate_limit(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{request.url.path}"
    now = time.monotonic()
    bucket = _hits[key]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _WRITE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many write requests; retry shortly",
        )
    bucket.append(now)
