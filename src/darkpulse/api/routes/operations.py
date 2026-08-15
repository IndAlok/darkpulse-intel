from typing import Any

from fastapi import APIRouter, Query, Request

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep, SettingsDep
from darkpulse.api.security import AdminDep
from darkpulse.ingestion.collectors.registry import SourceRegistry
from darkpulse.models import ApiEnvelope

router = APIRouter(prefix="/operations", tags=["Operations"])


@router.get("/sources", response_model=ApiEnvelope)
async def list_sources(
    request: Request, settings: SettingsDep, mongo: MongoDep, principal: AdminDep
) -> dict[str, Any]:
    registry = SourceRegistry.from_path(settings.collection.sources_path)
    sources = [
        {
            "source_id": source.source_id,
            "source_class": source.source_class.value,
            "enabled": source.enabled,
            "max_retries": source.max_retries,
        }
        for source in registry.sources
    ]
    await audit_event(
        mongo,
        request,
        principal,
        "operations.sources.read",
        target_type="source_registry",
    )
    return {
        "data": sorted(sources, key=lambda source: source["source_id"]),
        "meta": {
            "collection_control": (
                "CLI only; each live source requires existing authorization and policy review"
            )
        },
    }


@router.get("/processing", response_model=ApiEnvelope)
async def processing_status(
    request: Request, mongo: MongoDep, principal: AdminDep
) -> dict[str, Any]:
    grouped = await mongo.raw_ingest.aggregate(
        [{"$group": {"_id": "$processing.status", "count": {"$sum": 1}}}]
    ).to_list(length=20)
    await audit_event(
        mongo, request, principal, "operations.processing.read", target_type="processing"
    )
    return {"data": {str(item.get("_id") or "legacy"): item["count"] for item in grouped}}


@router.get("/onion-review", response_model=ApiEnvelope)
async def onion_review_status(
    request: Request, settings: SettingsDep, mongo: MongoDep, principal: AdminDep
) -> dict[str, Any]:
    registry = SourceRegistry.from_path(settings.collection.sources_path)
    onion_sources = [
        source
        for source in registry.sources
        if source.source_class.value in {"tor_market", "tor_forum"}
    ]
    approved = sum(1 for source in onion_sources if source.enabled)
    await audit_event(
        mongo,
        request,
        principal,
        "operations.onion_review.read",
        target_type="onion_review",
    )
    return {
        "data": {
            "reviewed_source_count": len(onion_sources),
            "approved_enabled_count": approved,
            "disabled_count": len(onion_sources) - approved,
            "policy": (
                "Reviewed onion sources are collected only through the approved CLI workflow."
            ),
        },
        "meta": {"source_details_redacted": True},
    }


@router.get("/audit", response_model=ApiEnvelope)
async def list_operations_audit(
    request: Request,
    mongo: MongoDep,
    principal: AdminDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    docs = (
        await mongo.audit.find(
            {},
            {
                "_id": 0,
                "occurred_at": 1,
                "actor": 1,
                "role": 1,
                "action": 1,
                "target_type": 1,
                "target_id": 1,
                "metadata": 1,
            },
        )
        .sort("occurred_at", -1)
        .to_list(length=limit)
    )
    await audit_event(
        mongo,
        request,
        principal,
        "operations.audit.read",
        target_type="audit_log",
        metadata={"limit": limit},
    )
    return {"data": docs, "meta": {"minimized": True, "limit": limit}}


@router.get("/collection-runs", response_model=ApiEnvelope)
async def list_collection_runs(
    request: Request,
    mongo: MongoDep,
    principal: AdminDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    docs = (
        await mongo.collection_runs.find({}, {"_id": 0})
        .sort("started_at", -1)
        .to_list(length=limit)
    )
    await audit_event(
        mongo,
        request,
        principal,
        "operations.collection_runs.read",
        target_type="collection_runs",
        metadata={"limit": limit},
    )
    latest = docs[0] if docs else None
    last_success = next(
        (item for item in docs if not item.get("failure_code") and not item.get("skipped")),
        None,
    )
    return {
        "data": docs,
        "meta": {
            "last_source_id": (latest or {}).get("source_id"),
            "last_started_at": (latest or {}).get("started_at"),
            "last_failure_code": (latest or {}).get("failure_code"),
            "last_success_at": (last_success or {}).get("started_at"),
            "next_due": "every 300s while the collector loop is running",
        },
    }
