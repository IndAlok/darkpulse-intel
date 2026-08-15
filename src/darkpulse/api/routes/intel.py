import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.excerpts import normalize_excerpt
from darkpulse.api.search_query import extract_intel_id, intel_id_candidates
from darkpulse.api.security import ViewerDep
from darkpulse.api.serializers import serialize_intel
from darkpulse.models import ApiEnvelope, IntelSummary, Pagination
from darkpulse.nlp.geo import resolve_neighborhood_names

router = APIRouter(prefix="/intel", tags=["Intelligence"])

MAX_LIMIT = 200


async def _find_intel(mongo: MongoDep, query: dict[str, Any]) -> dict[str, Any] | None:
    try:
        doc = await mongo.intel.find_one(query)
    except Exception:
        return None
    return doc if isinstance(doc, dict) and doc.get("intel_id") else None


async def fetch_intel_doc(mongo: MongoDep, raw_id: str) -> dict[str, Any] | None:
    for candidate in intel_id_candidates(raw_id):
        doc = await _find_intel(mongo, {"intel_id": candidate})
        if doc:
            return doc
    candidates = intel_id_candidates(raw_id)
    if not candidates:
        return None
    escaped = [re.escape(item) for item in candidates]
    return await _find_intel(
        mongo,
        {"intel_id": {"$regex": f"^({'|'.join(escaped)})$", "$options": "i"}},
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _named_values(values: Any, key: str) -> list[str]:
    if not isinstance(values, list):
        return []
    found: list[str] = []
    for item in values:
        text = str(item.get(key) or "").strip() if isinstance(item, dict) else str(item).strip()
        if text:
            found.append(text)
    return found


def _intel_summary(doc: dict[str, Any]) -> IntelSummary | None:
    captured_at = doc.get("captured_at")
    intel_id = str(doc.get("intel_id") or "").strip()
    ingest_id = str(doc.get("ingest_id") or "").strip()
    if not captured_at or not intel_id or not ingest_id:
        return None
    geo = _mapping(doc.get("geo"))
    entities = _mapping(doc.get("entities"))
    intent = _mapping(doc.get("intent"))
    severity = _mapping(doc.get("severity"))
    try:
        return IntelSummary(
            intel_id=intel_id,
            ingest_id=ingest_id,
            source_class=doc.get("source_class"),
            captured_at=captured_at,
            intent_label=str(intent.get("label") or ""),
            intent_score=float(intent.get("score") or 0.0),
            severity_score=float(severity.get("score") or 0.0),
            severity_band=str(severity.get("band") or ""),
            products=_named_values(doc.get("products"), "canonical"),
            neighborhood=str(geo.get("neighborhood") or ""),
            vendor_aliases=_named_values(entities.get("vendors"), "alias"),
            confidence=float(doc.get("confidence") or 0.0),
            tags=[str(tag) for tag in (doc.get("tags") or []) if tag],
        )
    except Exception:
        return None


@router.get("", response_model=ApiEnvelope)
async def list_intel(
    request: Request,
    mongo: MongoDep,
    principal: ViewerDep,
    product: str | None = None,
    neighborhood: str | None = None,
    severity_min: int | None = Query(default=None, ge=0, le=100),
    band: str | None = None,
    source_class: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    vendor: str | None = None,
    intel_id: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    filters: list[dict[str, Any]] = []

    resolved_id = None
    if intel_id:
        resolved = await fetch_intel_doc(mongo, intel_id)
        resolved_id = (resolved or {}).get("intel_id") or (
            extract_intel_id(intel_id) or intel_id.removeprefix("intel:").strip()
        )
    elif q:
        resolved = await fetch_intel_doc(mongo, q)
        resolved_id = (resolved or {}).get("intel_id") or extract_intel_id(q)

    if resolved_id:
        filters.append({"intel_id": str(resolved_id)})
    elif q:
        search_result = await mongo.search_intel(q, limit=limit)
        ids = [
            str(record.get("intel_id"))
            for record in search_result.get("records", [])
            if record.get("intel_id")
        ]
        if not ids:
            return {
                "data": [],
                "pagination": Pagination(cursor=None, limit=limit, total=0),
                "meta": {"search": q},
            }
        filters.append({"intel_id": {"$in": ids}})

    if product:
        escaped = re.escape(product)
        filters.append(
            {
                "$or": [
                    {"products.canonical": {"$regex": escaped, "$options": "i"}},
                    {"products.raw_term": {"$regex": escaped, "$options": "i"}},
                ]
            }
        )
    if neighborhood:
        names = resolve_neighborhood_names(neighborhood)
        filters.append(
            {"geo.neighborhood": {"$in": names}} if names else {"geo.neighborhood": neighborhood}
        )
    if severity_min is not None:
        query["severity.score"] = {"$gte": severity_min}
    if band:
        query["severity.band"] = band
    if source_class:
        query["source_class"] = source_class
    if vendor:
        query["entities.vendors.alias"] = vendor

    date_q: dict[str, Any] = {}
    if date_from:
        date_q["$gte"] = date_from.isoformat()
    if date_to:
        date_q["$lte"] = date_to.isoformat()
    if cursor:
        cursor_at, separator, cursor_id = cursor.partition("|")
        if not separator:
            date_q["$lt"] = cursor_at
            query["captured_at"] = date_q
        else:
            tiebreak_q: dict[str, Any] = {
                "captured_at": {
                    "$gte": date_q.get("$gte", cursor_at),
                    "$lte": cursor_at,
                },
                "intel_id": {"$lt": cursor_id},
            }
            query["$or"] = [
                {"captured_at": {**date_q, "$lt": cursor_at}},
                tiebreak_q,
            ]
    elif date_q:
        query["captured_at"] = date_q

    if filters:
        if query:
            query = {"$and": [query, *filters]}
        elif len(filters) == 1:
            query = filters[0]
        else:
            query = {"$and": filters}

    sort_spec = [("captured_at", -1), ("intel_id", -1)]
    cursor_obj = mongo.intel.find(query).sort(sort_spec).limit(limit + 1)
    results = await cursor_obj.to_list(length=limit + 1)

    has_next = len(results) > limit
    if has_next:
        results.pop()

    next_cursor = None
    if has_next and results:
        last = results[-1]
        next_cursor = f"{last.get('captured_at')}|{last.get('intel_id')}"

    data = []
    for doc in results:
        if not isinstance(doc, dict):
            continue
        summary = _intel_summary(doc)
        if summary:
            data.append(summary)

    total = await mongo.intel.count_documents(query)

    await audit_event(
        mongo,
        request,
        principal,
        "intel.list",
        target_type="intel",
        metadata={"result_count": len(data)},
    )
    return {
        "data": data,
        "pagination": Pagination(cursor=next_cursor, limit=limit, total=total),
        "meta": {},
    }


@router.get("/{intel_id}", response_model=ApiEnvelope)
async def get_intel(
    intel_id: str, request: Request, mongo: MongoDep, principal: ViewerDep
) -> dict[str, Any]:
    doc = await fetch_intel_doc(mongo, intel_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Intel record not found")

    payload = serialize_intel(doc)

    await audit_event(
        mongo, request, principal, "intel.read", target_type="intel", target_id=intel_id
    )
    return {
        "data": payload,
        "meta": {"trace_id": payload.get("trace_id")},
    }


@router.get("/{intel_id}/evidence", response_model=ApiEnvelope)
async def get_intel_evidence(
    intel_id: str, request: Request, mongo: MongoDep, principal: ViewerDep
) -> dict[str, Any]:
    intel = await fetch_intel_doc(mongo, intel_id)
    if not intel:
        raise HTTPException(status_code=404, detail="Intel record not found")
    raw = await mongo.raw_ingest.find_one({"ingest_id": intel.get("ingest_id")})
    if not isinstance(raw, dict):
        raw = {}
    snapshot = intel.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}
    if not raw and not snapshot:
        raise HTTPException(status_code=404, detail="Evidence metadata is unavailable")
    excerpt = snapshot.get("excerpt") or normalize_excerpt(str(raw.get("raw_content") or ""))
    await audit_event(
        mongo, request, principal, "intel.evidence.read", target_type="intel", target_id=intel_id
    )
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        evidence = snapshot
    return {
        "data": {
            "intel_id": intel_id,
            "trace_id": str(intel.get("trace_id") or "") or None,
            "source_ref": raw.get("source_ref", snapshot.get("source_ref")),
            "captured_at": raw.get("captured_at", snapshot.get("captured_at")),
            "source_sha256": evidence.get("source_sha256"),
            "content_sha256": evidence.get("content_sha256"),
            "excerpt": excerpt,
        },
        "meta": {
            "raw_excerpt_available": bool(raw),
            "provenance_snapshot_retained": bool(snapshot),
        },
    }
