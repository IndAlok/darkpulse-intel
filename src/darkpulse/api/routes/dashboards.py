from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep
from darkpulse.api.security import ViewerDep
from darkpulse.models import ApiEnvelope

router = APIRouter(prefix="/dashboards", tags=["Dashboards"])


@router.get("/trends", response_model=ApiEnvelope)
async def get_trends(
    request: Request,
    mongo: MongoDep,
    principal: ViewerDep,
    period: str = "30d",
) -> dict[str, Any]:
    days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
    start_date = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    pipeline: list[dict[str, Any]] = [
        {"$match": {"captured_at": {"$gte": start_date}}},
        {"$unwind": "$products"},
        {"$match": {"products.canonical": {"$ne": None}}},
        {
            "$project": {
                "date": {"$substr": ["$captured_at", 0, 10]},
                "product": "$products.canonical",
            }
        },
        {"$group": {"_id": {"date": "$date", "product": "$product"}, "count": {"$sum": 1}}},
        {"$sort": {"_id.date": 1}},
    ]

    cursor = mongo.intel.aggregate(pipeline)
    results = await cursor.to_list(length=10000)

    by_date: dict[str, dict[str, int]] = {}
    for doc in results:
        date = doc["_id"]["date"]
        product = doc["_id"]["product"]
        by_date.setdefault(date, {})[product] = doc["count"]

    data = [
        {"date": date, "count": sum(counts.values()), "products": counts}
        for date, counts in sorted(by_date.items())
    ]

    await audit_event(mongo, request, principal, "dashboard.trends.read", target_type="dashboard")
    return {"data": data, "meta": {}}


@router.get("/sources", response_model=ApiEnvelope)
async def get_sources(request: Request, mongo: MongoDep, principal: ViewerDep) -> dict[str, Any]:
    pipeline: list[dict[str, Any]] = [
        {
            "$group": {
                "_id": "$source_class",
                "record_count": {"$sum": 1},
                "avg_severity": {"$avg": "$severity.score"},
                "last_seen": {"$max": "$captured_at"},
            }
        },
        {"$sort": {"record_count": -1}},
    ]

    cursor = mongo.intel.aggregate(pipeline)
    results = await cursor.to_list(length=20)

    data = []
    for doc in results:
        if not doc["_id"]:
            continue
        data.append(
            {
                "source_class": doc["_id"],
                "record_count": doc["record_count"],
                "avg_severity": round(doc["avg_severity"], 2) if doc["avg_severity"] else 0,
                "last_seen": doc["last_seen"],
            }
        )

    await audit_event(mongo, request, principal, "dashboard.sources.read", target_type="dashboard")
    return {"data": data, "meta": {}}


@router.get("/geo", response_model=ApiEnvelope)
async def get_geo(request: Request, mongo: MongoDep, principal: ViewerDep) -> dict[str, Any]:
    pipeline: list[dict[str, Any]] = [
        {"$match": {"geo.neighborhood": {"$nin": [None, ""]}}},
        {
            "$group": {
                "_id": {"$toLower": "$geo.neighborhood"},
                "neighborhood": {"$first": "$geo.neighborhood"},
                "count": {"$sum": 1},
                "avg_severity": {"$avg": "$severity.score"},
                "product_lists": {"$push": "$products"},
            }
        },
        {"$sort": {"count": -1}},
    ]

    cursor = mongo.intel.aggregate(pipeline)
    results = await cursor.to_list(length=50)

    data = []
    for doc in results:
        products: list[str] = []
        seen: set[str] = set()
        for group in doc.get("product_lists") or []:
            if not isinstance(group, list):
                continue
            for item in group:
                name = ""
                if isinstance(item, dict):
                    name = str(item.get("canonical") or item.get("raw_term") or "")
                elif isinstance(item, str):
                    name = item
                key = name.casefold()
                if name and key not in seen:
                    seen.add(key)
                    products.append(name)
        data.append(
            {
                "neighborhood": doc.get("neighborhood") or doc["_id"],
                "count": doc["count"],
                "avg_severity": round(doc["avg_severity"], 2) if doc["avg_severity"] else 0,
                "top_products": products[:10],
            }
        )

    await audit_event(mongo, request, principal, "dashboard.geo.read", target_type="dashboard")
    return {"data": data, "meta": {}}
