import base64
import binascii
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.security import ViewerDep
from darkpulse.api.serializers import flatten_canonicals
from darkpulse.models import ApiEnvelope, Pagination

router = APIRouter(prefix="/actors", tags=["Actors"])

MAX_LIMIT = 200


@router.get("", response_model=ApiEnvelope)
async def list_actors(
    request: Request,
    mongo: MongoDep,
    principal: ViewerDep,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    pipeline: list[dict[str, Any]] = [
        {"$unwind": "$entities.vendors"},
        {"$match": {"entities.vendors.alias": {"$ne": ""}}},
    ]

    if q:
        escaped = re.escape(q)
        pipeline.append(
            {"$match": {"entities.vendors.alias": {"$regex": escaped, "$options": "i"}}}
        )

    grouped = [
        {
            "$group": {
                "_id": "$entities.vendors.alias",
                "platform": {"$first": "$entities.vendors.platform"},
                "listing_count": {"$sum": 1},
                "first_seen": {"$min": "$captured_at"},
                "last_seen": {"$max": "$captured_at"},
                "avg_severity": {"$avg": "$severity.score"},
                "products": {"$addToSet": "$products"},
                "neighborhoods": {"$addToSet": "$geo.neighborhood"},
            }
        },
    ]
    total_cursor = mongo.intel.aggregate([*pipeline, *grouped, {"$count": "total"}])
    total_docs = await total_cursor.to_list(length=1)
    total = total_docs[0]["total"] if total_docs else 0
    pipeline.extend(grouped)
    if cursor:
        if len(cursor) > 512:
            raise HTTPException(status_code=400, detail="Invalid actor cursor")
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            pipeline.append(
                {
                    "$match": {
                        "$or": [
                            {"listing_count": {"$lt": int(decoded["count"])}},
                            {
                                "listing_count": int(decoded["count"]),
                                "_id": {"$gt": str(decoded["alias"])},
                            },
                        ]
                    }
                }
            )
        except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
            raise HTTPException(status_code=400, detail="Invalid actor cursor") from None
    pipeline.extend([{"$sort": {"listing_count": -1, "_id": 1}}, {"$limit": limit + 1}])

    cursor_obj = mongo.intel.aggregate(pipeline)
    results = await cursor_obj.to_list(length=limit + 1)
    has_next = len(results) > limit
    if has_next:
        results.pop()

    data = []
    for doc in results:
        flat_prods = flatten_canonicals(doc.get("products", []))
        neighborhoods = [n for n in doc.get("neighborhoods", []) if n]

        data.append(
            {
                "actor_id": doc["_id"],
                "alias": doc["_id"],
                "platform": doc.get("platform", ""),
                "listing_count": doc["listing_count"],
                "first_seen": doc["first_seen"],
                "last_seen": doc["last_seen"],
                "avg_severity": round(doc["avg_severity"], 2) if doc["avg_severity"] else 0,
                "products": flat_prods[:10],
                "neighborhoods": neighborhoods[:5],
            }
        )

    next_cursor = None
    if has_next and results:
        last = results[-1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"count": last["listing_count"], "alias": last["_id"]}).encode()
        ).decode()
    await audit_event(
        mongo,
        request,
        principal,
        "actors.list",
        target_type="actor",
        metadata={"result_count": len(data)},
    )
    return {
        "data": data,
        "pagination": Pagination(cursor=next_cursor, limit=limit, total=total),
        "meta": {},
    }


@router.get("/{actor_id}", response_model=ApiEnvelope)
async def get_actor(
    actor_id: str, request: Request, mongo: MongoDep, principal: ViewerDep
) -> dict[str, Any]:
    alias = actor_id.removeprefix("vendor:")
    pipeline: list[dict[str, Any]] = [
        {"$unwind": "$entities.vendors"},
        {"$match": {"entities.vendors.alias": alias}},
        {
            "$group": {
                "_id": "$entities.vendors.alias",
                "platform": {"$first": "$entities.vendors.platform"},
                "listing_count": {"$sum": 1},
                "first_seen": {"$min": "$captured_at"},
                "last_seen": {"$max": "$captured_at"},
                "avg_severity": {"$avg": "$severity.score"},
                "products": {"$addToSet": "$products"},
                "neighborhoods": {"$addToSet": "$geo.neighborhood"},
            }
        },
    ]

    cursor_obj = mongo.intel.aggregate(pipeline)
    results = await cursor_obj.to_list(length=1)

    if not results:
        raise HTTPException(status_code=404, detail="Actor not found")

    doc = results[0]

    timeline_cursor = (
        mongo.intel.find({"entities.vendors.alias": alias}).sort("captured_at", -1).limit(20)
    )

    timeline = []
    for item in await timeline_cursor.to_list(length=20):
        timeline.append(
            {
                "intel_id": item["intel_id"],
                "captured_at": item["captured_at"],
                "intent": item.get("intent", {}).get("label"),
                "severity": item.get("severity", {}).get("band"),
            }
        )

    data = {
        "actor_id": doc["_id"],
        "alias": doc["_id"],
        "platform": doc.get("platform", ""),
        "listing_count": doc["listing_count"],
        "first_seen": doc["first_seen"],
        "last_seen": doc["last_seen"],
        "avg_severity": round(doc["avg_severity"], 2) if doc["avg_severity"] else 0,
        "products": flatten_canonicals(doc.get("products", []))[:10],
        "neighborhoods": [n for n in doc.get("neighborhoods", []) if n][:5],
        "timeline": timeline,
    }

    await audit_event(
        mongo, request, principal, "actors.read", target_type="actor", target_id=actor_id
    )
    return {"data": data, "meta": {}}
