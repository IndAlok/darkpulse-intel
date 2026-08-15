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
from darkpulse.models import ApiEnvelope, SlangEntry, SlangListResponse, SlangResponse, SlangUpdate

router = APIRouter(prefix="/slang", tags=["Slang"])


def _response(doc: dict[str, Any], usage_count: int = 0) -> SlangResponse:
    return SlangResponse(
        id=str(doc["_id"]),
        term=doc["term"],
        meaning=doc["meaning"],
        lang=doc.get("lang", "en"),
        confidence=doc.get("confidence", 1.0),
        newly_discovered=doc.get("newly_discovered", False),
        review_status=doc.get("review_status", "approved"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
        usage_count=usage_count,
    )


async def _usage_counts(db: MongoDep) -> dict[str, int]:
    cursor = db.intel.aggregate(
        [
            {"$unwind": "$slang_decoded"},
            {"$group": {"_id": "$slang_decoded.term", "count": {"$sum": 1}}},
        ]
    )
    if inspect.isawaitable(cursor):
        cursor = await cursor
    to_list = getattr(cursor, "to_list", None)
    grouped = await to_list(length=2000) if to_list else []
    if inspect.isawaitable(grouped):
        grouped = await grouped
    if not isinstance(grouped, list):
        return {}
    return {str(item["_id"]).casefold(): int(item["count"]) for item in grouped if item.get("_id")}


@router.get("", response_model=SlangListResponse)
async def list_slang(
    db: MongoDep,
    _: ViewerDep,
    lang: str | None = None,
    newly_discovered: bool | None = None,
    review_status: str | None = None,
) -> SlangListResponse:
    query: dict[str, Any] = {}
    if lang is not None:
        query["lang"] = lang
    if newly_discovered is not None:
        query["newly_discovered"] = newly_discovered
    if review_status is not None:
        query["review_status"] = review_status
    docs = await db.slang.find(query).sort("updated_at", -1).to_list(length=200)
    counts = await _usage_counts(db)
    return SlangListResponse(
        data=[_response(doc, counts.get(str(doc.get("term", "")).casefold(), 0)) for doc in docs]
    )


@router.get("/candidates", response_model=SlangListResponse)
async def list_candidates(db: MongoDep, _: ViewerDep, limit: int = 50) -> SlangListResponse:
    cursor = db.slang.find({"newly_discovered": True}).sort("updated_at", -1).limit(min(limit, 200))
    docs = await cursor.to_list(length=min(limit, 200))
    counts = await _usage_counts(db)
    return SlangListResponse(
        data=[_response(doc, counts.get(str(doc.get("term", "")).casefold(), 0)) for doc in docs]
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiEnvelope)
async def create_slang_entry(
    req: SlangEntry, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    now = datetime.now(UTC)
    doc = {
        "_id": str(uuid.uuid4()),
        **req.model_dump(),
        "review_status": "pending" if req.newly_discovered else "approved",
        "created_at": now,
        "updated_at": now,
    }
    await db.slang.insert_one(doc)
    await audit_event(
        db, request, principal, "slang.create", target_type="slang", target_id=doc["_id"]
    )
    return {"data": _response(doc), "meta": {}}


@router.put("/{slang_id}", response_model=ApiEnvelope)
async def update_slang_entry(
    slang_id: str, req: SlangUpdate, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    doc = await db.slang.find_one_and_update(
        {"_id": slang_id},
        {"$set": {**req.model_dump(), "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Slang entry not found")
    await audit_event(
        db, request, principal, "slang.update", target_type="slang", target_id=slang_id
    )
    return {"data": _response(doc), "meta": {}}


@router.post("/{slang_id}/approve", response_model=ApiEnvelope)
async def approve_candidate(
    slang_id: str, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    doc = await db.slang.find_one_and_update(
        {"_id": slang_id},
        {
            "$set": {
                "newly_discovered": False,
                "review_status": "approved",
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Slang entry not found")
    await audit_event(
        db, request, principal, "slang.approve", target_type="slang", target_id=slang_id
    )
    return {"data": _response(doc), "meta": {}}


@router.post("/{slang_id}/reject", response_model=ApiEnvelope)
async def reject_candidate(
    slang_id: str, request: Request, db: MongoDep, principal: AnalystDep
) -> dict[str, Any]:
    doc = await db.slang.find_one_and_update(
        {"_id": slang_id},
        {
            "$set": {
                "newly_discovered": False,
                "review_status": "rejected",
                "updated_at": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Slang entry not found")
    await audit_event(
        db, request, principal, "slang.reject", target_type="slang", target_id=slang_id
    )
    return {"data": _response(doc), "meta": {}}


@router.delete("/{slang_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slang_entry(
    slang_id: str, request: Request, db: MongoDep, principal: AnalystDep
) -> None:
    result = await db.slang.delete_one({"_id": slang_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Slang entry not found")
    await audit_event(
        db, request, principal, "slang.delete", target_type="slang", target_id=slang_id
    )
