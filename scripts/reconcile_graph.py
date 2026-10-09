"""Reconcile graph drift: list intel rows missing a Neo4j IntelRef, optionally re-queue.

Dry run (default) prints ids only. --apply re-queues the raw rows by resetting
processing.status to pending. Never deletes data.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from darkpulse.config import get_settings
from darkpulse.storage.mongodb import MongoManager
from darkpulse.storage.neo4j import Neo4jManager

QUERY = "MATCH (i:IntelRef) WHERE i.intel_id IN $ids RETURN i.intel_id AS intel_id"


async def find_drift(mongo: MongoManager, neo4j: Neo4jManager) -> list[dict[str, Any]]:
    intel_ids = [doc["intel_id"] async for doc in mongo.intel.find({}, {"intel_id": 1})]
    if not intel_ids:
        return []
    async with neo4j._driver.session() as session:
        rows = await session.run(QUERY, ids=intel_ids).data()
    present = {r["intel_id"] for r in rows}
    return [{"intel_id": i} for i in intel_ids if i not in present]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="List intel rows missing a Neo4j IntelRef; optionally re-queue."
    )
    parser.add_argument(
        "--apply", action="store_true", help="re-queue drifted raw rows (default: dry run)"
    )
    args = parser.parse_args()

    settings = get_settings()
    mongo = MongoManager(settings.mongo)
    neo4j = Neo4jManager(settings.neo4j)
    await mongo.connect()
    await neo4j.connect()

    drift = await find_drift(mongo, neo4j)
    if not drift:
        print("no drift: every intel row has an IntelRef")
        return 0

    for row in drift:
        print(f"drift: {row['intel_id']}")

    if not args.apply:
        print(f"{len(drift)} drifted rows (dry run; pass --apply to re-queue)")
        return 0

    result = await mongo.raw_ingest.update_many(
        {"intel_id": {"$in": [r["intel_id"] for r in drift]}},
        {"$set": {"processing.status": "pending", "processing.lease_expires_at": None}},
    )
    print(f"re-queued {result.modified_count} raw rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
