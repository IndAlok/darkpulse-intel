from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.security import ViewerDep
from darkpulse.api.serializers import serialize_intel
from darkpulse.models import ApiEnvelope, Pagination

router = APIRouter(prefix="/search", tags=["Search"])

MAX_LIMIT = 200
KNOWN_LANGS = frozenset(
    {
        "en",
        "hi",
        "gu",
        "mr",
        "pa",
        "bn",
        "ta",
        "te",
        "kn",
        "ml",
        "ur",
        "ar",
        "ne",
        "si",
        "hinglish",
    }
)


@router.get("", response_model=ApiEnvelope)
async def search(
    request: Request,
    mongo: MongoDep,
    principal: ViewerDep,
    q: str = Query(..., min_length=1, max_length=500),
    lang: str | None = Query(default=None, max_length=8),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    if lang is not None and lang.casefold() not in KNOWN_LANGS:
        raise HTTPException(status_code=422, detail="Unsupported language filter")
    result = await mongo.search_intel(query=q, limit=limit, lang=lang)

    await audit_event(
        mongo,
        request,
        principal,
        "search.execute",
        target_type="intel_search",
        metadata={"result_count": len(result["records"])},
    )
    return {
        "data": [serialize_intel(record) for record in result["records"]],
        "pagination": Pagination(cursor=None, limit=limit, total=result["total"]),
        "meta": {},
    }
