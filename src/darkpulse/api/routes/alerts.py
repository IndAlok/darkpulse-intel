from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.security import _ROLE_ORDER, AnalystDep, ViewerDep, websocket_principal
from darkpulse.models import AlertConfig, AlertHistoryResponse, ApiEnvelope, Pagination

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_active_connections: set[WebSocket] = set()


async def broadcast_alert(alert_payload: dict[str, Any]) -> None:
    if not _active_connections:
        return

    disconnected = set()
    for ws in _active_connections:
        try:
            await ws.send_json(alert_payload)
        except Exception:
            disconnected.add(ws)

    for ws in disconnected:
        _active_connections.remove(ws)


@router.get("/config", response_model=ApiEnvelope)
async def get_alert_config(db: MongoDep, _: ViewerDep) -> dict[str, Any]:
    doc = await db.alerts_config.find_one({"_id": "default"})
    if not doc:
        return {"data": AlertConfig(rules=[]), "meta": {}}
    return {"data": AlertConfig(rules=doc.get("rules", [])), "meta": {}}


@router.put("/config", response_model=ApiEnvelope)
async def update_alert_config(
    req: AlertConfig,
    request: Request,
    db: MongoDep,
    principal: AnalystDep,
) -> dict[str, Any]:
    rules = [rule.model_dump() for rule in req.rules]
    await db.alerts_config.update_one({"_id": "default"}, {"$set": {"rules": rules}}, upsert=True)
    await audit_event(
        db,
        request,
        principal,
        "alerts.config.update",
        target_type="alert_config",
        target_id="default",
        metadata={"rule_count": len(rules)},
    )
    return {"data": req, "meta": {}}


@router.get("/history", response_model=AlertHistoryResponse)
async def get_alert_history(
    db: MongoDep,
    _: ViewerDep,
    cursor: str | None = None,
    limit: int = 50,
) -> AlertHistoryResponse:
    query: dict[str, Any] = {}
    if cursor:
        query["_id"] = {"$lt": cursor}

    safe_limit = min(max(limit, 1), 200)
    db_cursor = db.alerts_history.find(query).sort("_id", -1)
    docs = await db_cursor.to_list(length=safe_limit + 1)
    has_next = len(docs) > safe_limit
    if has_next:
        docs.pop()

    for doc in docs:
        doc["id"] = str(doc.pop("_id", ""))
        doc.setdefault("acknowledged", False)
        doc.setdefault("assignee", None)
        doc.setdefault("resolved_at", None)

    total = await db.alerts_history.count_documents(query)

    return AlertHistoryResponse(
        data=docs,
        pagination=Pagination(
            cursor=docs[-1]["id"] if has_next and docs else None, limit=safe_limit, total=total
        ),
    )


class AlertPatch(BaseModel):
    acknowledged: bool | None = None
    assignee: str | None = Field(default=None, max_length=200)
    resolved: bool | None = None


@router.patch("/history/{alert_id}", response_model=ApiEnvelope)
async def patch_alert(
    alert_id: str,
    req: AlertPatch,
    request: Request,
    db: MongoDep,
    principal: AnalystDep,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if req.acknowledged is not None:
        updates["acknowledged"] = req.acknowledged
    if req.assignee is not None:
        updates["assignee"] = req.assignee
    if req.resolved is True:
        updates["resolved_at"] = datetime.now(UTC)
    elif req.resolved is False:
        updates["resolved_at"] = None
    if not updates:
        raise HTTPException(status_code=422, detail="No alert updates supplied")
    query: dict[str, Any] = {"_id": alert_id}
    try:
        from bson import ObjectId

        if ObjectId.is_valid(alert_id):
            query = {"$or": [{"_id": alert_id}, {"_id": ObjectId(alert_id)}]}
    except Exception:
        query = {"_id": alert_id}
    doc = await db.alerts_history.find_one_and_update(
        query,
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Alert not found")
    doc["id"] = str(doc.pop("_id", ""))
    await audit_event(
        db, request, principal, "alerts.update", target_type="alert", target_id=alert_id
    )
    return {"data": doc, "meta": {}}


@router.websocket("/ws")
async def websocket_alerts(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    settings = websocket.app.state.settings
    allowed = (
        {"http://localhost:5173", "http://localhost:3000"}
        if settings.service.environment == "development"
        else {settings.service.frontend_origin}
    )
    principal = websocket_principal(websocket.query_params.get("access_token"), settings)
    if (
        principal is None
        or _ROLE_ORDER[principal.role] < _ROLE_ORDER["viewer"]
        or (origin and origin not in allowed)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    _active_connections.add(websocket)
    await audit_event(
        websocket.app.state.mongo,
        websocket,
        principal,
        "alerts.websocket.connect",
        target_type="websocket",
    )
    logger.info("websocket.client_connected", client=websocket.client)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket.client_disconnected")
    finally:
        if websocket in _active_connections:
            _active_connections.remove(websocket)
