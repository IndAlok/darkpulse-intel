from __future__ import annotations

import inspect
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

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
_BACKFILL_LIMIT = 2000


def _observed_text(doc: dict[str, Any]) -> str:
    products = doc.get("products") or []
    slang = doc.get("slang_decoded") or []
    return " ".join(
        [
            str(doc.get("translated_text", "")),
            *[
                str(product.get("canonical", ""))
                for product in products
                if isinstance(product, dict)
            ],
            *[str(match.get("term", "")) for match in slang if isinstance(match, dict)],
        ]
    ).casefold()


async def _name_taken(db: MongoDep, name: str, exclude_id: str | None = None) -> bool:
    query: dict[str, Any] = {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    found = await db.watchlists.find_one(query)
    return isinstance(found, dict)


async def _load_intel_sample(db: MongoDep) -> tuple[list[dict[str, Any]], bool]:
    finder = db.intel.find(
        {},
        {
            "intel_id": 1,
            "translated_text": 1,
            "products": 1,
            "slang_decoded": 1,
            "severity.score": 1,
        },
    )
    if inspect.isawaitable(finder):
        finder = await finder
    sort = getattr(finder, "sort", None)
    cursor = sort("captured_at", -1) if sort else finder
    if inspect.isawaitable(cursor):
        cursor = await cursor
    to_list = getattr(cursor, "to_list", None)
    docs = await to_list(length=_BACKFILL_LIMIT + 1) if to_list else []
    if inspect.isawaitable(docs):
        docs = await docs
    if not isinstance(docs, list):
        return [], False
    truncated = len(docs) > _BACKFILL_LIMIT
    return [doc for doc in docs[:_BACKFILL_LIMIT] if isinstance(doc, dict)], truncated


async def _backfill_watchlist(
    db: MongoDep, watchlist_id: str, name: str, terms: list[str], notify: bool
) -> tuple[int, bool]:
    from darkpulse.broker.processor import _term_in_text

    docs, truncated = await _load_intel_sample(db)
    matched = 0
    for doc in docs:
        hits = [term for term in terms if _term_in_text(str(term), _observed_text(doc))]
        if not hits:
            continue
        matched += 1
        if not notify or not doc.get("intel_id"):
            continue
        score = (doc.get("severity") or {}).get("score", 0)
        alert = {
            "_id": f"{doc['intel_id']}:watch:{watchlist_id}",
            "rule_name": f"Watchlist: {name}",
            "intel_id": doc["intel_id"],
            "triggered_at": datetime.now(UTC),
            "severity_score": score,
            "context": f"Matched monitored terms: {', '.join(hits[:10])}",
            "watchlist_id": watchlist_id,
            "acknowledged": False,
            "assignee": None,
            "resolved_at": None,
        }
        try:
            await db.alerts_history.insert_one(alert)
        except DuplicateKeyError:
            continue
    return matched, truncated


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
    if await _name_taken(db, req.name):
        raise HTTPException(status_code=409, detail="Watchlist name already exists")
    now = datetime.now(UTC)
    doc = {
        "_id": str(uuid.uuid4()),
        **req.model_dump(),
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.watchlists.insert_one(doc)
    try:
        await audit_event(
            db,
            request,
            principal,
            "watchlist.create",
            target_type="watchlist",
            target_id=doc["_id"],
        )
    except Exception:
        await db.watchlists.delete_one({"_id": doc["_id"]})
        raise
    matched, truncated = await _backfill_watchlist(
        db, doc["_id"], doc["name"], doc["terms"], bool(doc.get("notify", True))
    )
    return {"data": _response(doc, matched), "meta": {"truncated": truncated}}


@router.put("/{watchlist_id}", response_model=ApiEnvelope)
async def update_watchlist(
    watchlist_id: str, req: WatchlistUpdate, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    updates = req.model_dump(exclude_unset=True)
    if "name" in updates and await _name_taken(db, str(updates["name"]), watchlist_id):
        raise HTTPException(status_code=409, detail="Watchlist name already exists")
    result = await db.watchlists.find_one_and_update(
        {"_id": watchlist_id},
        {"$set": {**updates, "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    await audit_event(
        db, request, principal, "watchlist.update", target_type="watchlist", target_id=watchlist_id
    )
    matched, truncated = (0, False)
    if "terms" in updates or "notify" in updates:
        matched, truncated = await _backfill_watchlist(
            db,
            watchlist_id,
            str(result.get("name", "")),
            list(result.get("terms") or []),
            bool(result.get("notify", True)),
        )
    return {"data": _response(result, matched), "meta": {"truncated": truncated}}


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
