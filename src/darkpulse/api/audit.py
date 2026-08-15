from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request
from starlette.websockets import WebSocket

from darkpulse.api.security import Principal
from darkpulse.storage.mongodb import MongoManager

logger = structlog.get_logger(__name__)


async def audit_event(
    db: MongoManager,
    request: Request | WebSocket,
    principal: Principal,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        await db.audit.insert_one(
            {
                "occurred_at": datetime.now(UTC),
                "actor": principal.subject,
                "role": principal.role,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "path": request.url.path,
                "method": getattr(request, "method", "WS"),
                "ip": request.client.host if request.client else None,
                "metadata": metadata or {},
            }
        )
    except Exception:
        logger.exception("audit.write_failed", action=action)
