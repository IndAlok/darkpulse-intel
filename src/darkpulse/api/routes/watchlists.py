from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pymongo import ReturnDocument

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.security import AnalystDep, ViewerDep
from darkpulse.models import (
    ApiEnvelope,
    WatchlistCreate,
    WatchlistListResponse,
    WatchlistResponse,
    WatchlistUpdate,
)

router = APIRouter(prefix="/watchlists", tags=["Watchlists"])


def _response(doc: dict[str, Any], match_count: int = 0) -> WatchlistResponse:
    return WatchlistResponse(
        id=str(doc["_id"]),
        name=doc["name"],
        terms=doc["terms"],
        notify=doc.get("notify", True),
        enabled=doc.get("enabled", True),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
        match_count=match_count,
    )


async def _match_counts(db: MongoDep) -> dict[str, int]:
    cursor = db.alerts_history.aggregate(
        [{"$group": {"_id": "$watchlist_id", "count": {"$sum": 1}}}]
    )
    if inspect.isawaitable(cursor):
        cursor = await cursor
    to_list = getattr(cursor, "to_list", None)
    grouped = await to_list(length=500) if to_list else []
    if inspect.isawaitable(grouped):
        grouped = await grouped
    if not isinstance(grouped, list):
        return {}
    return {str(item["_id"]): int(item["count"]) for item in grouped if item.get("_id")}


@router.get("", response_model=WatchlistListResponse)
async def list_watchlists(db: MongoDep, _: ViewerDep) -> WatchlistListResponse:
    docs = await db.watchlists.find({}).sort("updated_at", -1).to_list(length=100)
    counts = await _match_counts(db)
    return WatchlistListResponse(
        data=[_response(doc, counts.get(str(doc["_id"]), 0)) for doc in docs]
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiEnvelope)
async def create_watchlist(
    req: WatchlistCreate, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc = {
        "_id": str(uuid.uuid4()),
        **req.model_dump(),
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.watchlists.insert_one(doc)
    await audit_event(
        db, request, principal, "watchlist.create", target_type="watchlist", target_id=doc["_id"]
    )
    return {"data": _response(doc), "meta": {}}


@router.put("/{watchlist_id}", response_model=ApiEnvelope)
async def update_watchlist(
    watchlist_id: str, req: WatchlistUpdate, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    result = await db.watchlists.find_one_and_update(
        {"_id": watchlist_id},
        {"$set": {**req.model_dump(), "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    await audit_event(
        db, request, principal, "watchlist.update", target_type="watchlist", target_id=watchlist_id
    )
    return {"data": _response(result), "meta": {}}


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    watchlist_id: str, request: Request, db: MongoDep, principal: AnalystDep
) -> None:
    result = await db.watchlists.delete_one({"_id": watchlist_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    await audit_event(
        db, request, principal, "watchlist.delete", target_type="watchlist", target_id=watchlist_id
    )
