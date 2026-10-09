import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.security import (
    _ROLE_ORDER,
    AnalystDep,
    Principal,
    ViewerDep,
    consume_ticket,
    mint_ticket,
    open_mode_principal,
)
from darkpulse.config import allowed_origins
from darkpulse.models import AlertConfig, AlertHistoryResponse, ApiEnvelope, Pagination

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/alerts", tags=["Alerts"])
ws_router = APIRouter(prefix="/alerts", tags=["Alerts"])

_MAX_SOCKETS_PER_SUBJECT = 4
_MAX_CLIENT_FRAME = 32
_SEND_TIMEOUT_SECONDS = 2.0
_IDLE_SECONDS = 45.0
_VIEWER_HIDDEN = ("wallet", "wallets", "pgp", "contact", "contacts", "source_ref", "phone", "email")
_connections: dict[WebSocket, Principal] = {}
_lock = asyncio.Lock()
_ALERT_CHANNEL = "dp:alerts"
_relay_client: Any = None
_relay_task: asyncio.Task[None] | None = None


_ID_ALPHABET = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:"
)


def _validate_id(raw_id: str, field_name: str) -> str:
    if len(raw_id) > 512 or not set(raw_id) <= _ID_ALPHABET:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} contains unsupported characters or is too long",
        )
    return raw_id


def _alert_id_values(raw_id: str) -> list[Any]:
    values: list[Any] = [raw_id]
    try:
        from bson import ObjectId

        if len(raw_id) == 24 and ObjectId.is_valid(raw_id):
            values.append(ObjectId(raw_id))
    except Exception:
        return values
    return values


def history_page_query(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    triggered, separator, raw_id = cursor.partition("|")
    if not separator:
        raw_id = triggered
        triggered = ""
    id_clauses = [{"_id": {"$lt": value}} for value in _alert_id_values(raw_id)]
    if not triggered:
        return id_clauses[0] if len(id_clauses) == 1 else {"$or": id_clauses}
    moments: list[Any] = [triggered]
    with suppress(ValueError):
        moments.append(datetime.fromisoformat(triggered.replace("Z", "+00:00")))
    clauses: list[dict[str, Any]] = []
    for moment in moments:
        clauses.append({"triggered_at": {"$lt": moment}})
        clauses.extend({"$and": [{"triggered_at": moment}, clause]} for clause in id_clauses)
    return {"$or": clauses}


def _cursor_token(doc: dict[str, Any]) -> str:
    triggered = doc.get("triggered_at")
    stamp = triggered.isoformat() if isinstance(triggered, datetime) else str(triggered or "")
    return f"{stamp}|{doc.get('id', '')}"


def _visible_alert(payload: dict[str, Any], principal: Principal) -> dict[str, Any] | None:
    audience = payload.get("audience", "viewer")
    if _ROLE_ORDER[principal.role] < _ROLE_ORDER.get(audience, 0):
        return None
    if principal.role != "viewer":
        return payload
    return {key: value for key, value in payload.items() if key not in _VIEWER_HIDDEN}


async def _deliver_local(alert_payload: dict[str, Any]) -> None:
    async with _lock:
        snapshot = list(_connections.items())
    if not snapshot:
        return
    disconnected: list[WebSocket] = []
    for websocket, principal in snapshot:
        visible = _visible_alert(alert_payload, principal)
        if visible is None:
            continue
        try:
            await asyncio.wait_for(
                websocket.send_json(visible),
                timeout=_SEND_TIMEOUT_SECONDS,
            )
        except Exception:
            disconnected.append(websocket)
    if not disconnected:
        return
    async with _lock:
        for websocket in disconnected:
            _connections.pop(websocket, None)


async def broadcast_alert(alert_payload: dict[str, Any]) -> None:
    client = _relay_client
    if client is not None:
        try:
            await client.publish(_ALERT_CHANNEL, json.dumps(alert_payload, default=str))
            return
        except Exception:
            logger.warning("alerts.redis_publish_failed")
    await _deliver_local(alert_payload)


async def _relay_loop(subscriber: Any) -> None:
    pubsub = subscriber.pubsub()
    try:
        await pubsub.subscribe(_ALERT_CHANNEL)
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message or message.get("type") != "message":
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                await _deliver_local(payload)
    finally:
        await pubsub.aclose()
        await subscriber.aclose()


async def start_alert_relay(url: str | None) -> None:
    global _relay_client, _relay_task
    from darkpulse.api.security import _redis_disabled

    if _redis_disabled or not url or _relay_task is not None:
        return
    from redis.asyncio import Redis

    publisher = Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.2)
    subscriber = Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.2)
    try:
        await publisher.ping()
    except Exception:
        logger.warning("alerts.redis_unavailable")
        await publisher.aclose()
        await subscriber.aclose()
        return
    _relay_client = publisher
    _relay_task = asyncio.create_task(_relay_loop(subscriber), name="alert-relay")


async def stop_alert_relay() -> None:
    global _relay_client, _relay_task
    task = _relay_task
    _relay_task = None
    publisher = _relay_client
    _relay_client = None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if publisher is not None:
        await publisher.aclose()


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
    limit: int = Query(default=50, ge=1, le=200),
) -> AlertHistoryResponse:
    query = history_page_query(cursor)
    safe_limit = limit
    db_cursor = db.alerts_history.find(query).sort([("triggered_at", -1), ("_id", -1)])
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
            cursor=_cursor_token(docs[-1]) if has_next and docs else None,
            limit=safe_limit,
            total=total,
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
    _validate_id(alert_id, "alert_id")
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
    await audit_event(
        db, request, principal, "alerts.update", target_type="alert", target_id=alert_id
    )
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
    return {"data": doc, "meta": {}}


@router.post("/ws-ticket", response_model=ApiEnvelope)
async def ws_ticket(principal: ViewerDep) -> dict[str, Any]:
    return {"data": {"ticket": mint_ticket(principal)}, "meta": {}}


@ws_router.websocket("/ws")
async def websocket_alerts(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    settings = websocket.app.state.settings
    allowed = allowed_origins(settings)
    if websocket.query_params.get("access_token"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    peer = websocket.client.host if websocket.client else None
    open_principal = None if settings.auth.enabled else open_mode_principal(settings, peer)
    origin_ok = origin in allowed if origin else open_principal is not None
    ticket = websocket.query_params.get("ticket")
    principal = None
    if origin_ok:
        principal = consume_ticket(ticket) if ticket else open_principal
    if principal is None or _ROLE_ORDER[principal.role] < _ROLE_ORDER["viewer"]:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    async with _lock:
        open_for_subject = sum(
            1 for item in _connections.values() if item.subject == principal.subject
        )
        admitted = open_for_subject < _MAX_SOCKETS_PER_SUBJECT
        if admitted:
            _connections[websocket] = principal
    if not admitted:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await audit_event(
        websocket.app.state.mongo,
        websocket,
        principal,
        "alerts.websocket.connect",
        target_type="websocket",
    )
    logger.info("websocket.client_connected", client=websocket.client)
    try:
        misses = 0
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=_IDLE_SECONDS)
            except TimeoutError:
                misses += 1
                if misses > 1:
                    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                    break
                try:
                    await asyncio.wait_for(
                        websocket.send_json({"type": "ping"}), timeout=_SEND_TIMEOUT_SECONDS
                    )
                except Exception:
                    break
                continue
            misses = 0
            if message != "ping" or len(message) > _MAX_CLIENT_FRAME:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                break
            await asyncio.wait_for(
                websocket.send_json({"type": "pong"}), timeout=_SEND_TIMEOUT_SECONDS
            )
    except WebSocketDisconnect:
        logger.info("websocket.client_disconnected")
    finally:
        async with _lock:
            _connections.pop(websocket, None)
