"""Publish a synthetic Surat corpus so every desk screen has records to show."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from darkpulse.cli import _pipeline_resources
from darkpulse.config import get_settings
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType, SourceClass

WALLET = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
PGP = "A1B2 C3D4 E5F6 0718 293A 4B5C 6D7E 8F90 1234 ABCD"

OBSERVATIONS: list[tuple[SourceClass, str, str, int]] = [
    (
        SourceClass.TOR_MARKET,
        "demo://surat/rivergate-vesu",
        f"vendor: rivergate. Observed public listing: snow for sale, ship from vesu, Surat. 2 grams. Wallet {WALLET}. PGP {PGP}.",
        0,
    ),
    (
        SourceClass.TELEGRAM,
        "demo://surat/rivergate-adajan",
        f"vendor: rivergate. Follow-up note: ice available, ship from adajan, Surat. Fast shipping. Wallet {WALLET}.",
        1,
    ),
    (
        SourceClass.TOR_MARKET,
        "demo://surat/stationbook-varachha",
        f"vendor: stationbook. Observed listing: molly for sale, ship from varachha, Surat. 5 pills. Wallet {WALLET}. PGP {PGP}.",
        1,
    ),
    (
        SourceClass.SURFACE_MARKET,
        "demo://surat/westlane-katargam",
        "vendor: westlane. Observed listing: weed for sale, ship from katargam, Surat. 10 grams. Ready to ship.",
        2,
    ),
    (
        SourceClass.TOR_FORUM,
        "demo://surat/rivergate-udhna",
        "vendor: rivergate. Forum post: coke for sale, ship from udhna, Surat. Sample available.",
        3,
    ),
    (
        SourceClass.TELEGRAM,
        "demo://surat/stationbook-piplod",
        "vendor: stationbook. Channel note: maal for sale, ship from piplod, Surat. Quick delivery.",
        4,
    ),
    (
        SourceClass.TOR_MARKET,
        "demo://surat/westlane-athwa",
        "vendor: westlane. Observed listing: brown sugar for sale, ship from athwa, Surat. 1 gram.",
        5,
    ),
    (
        SourceClass.SOCIAL,
        "demo://surat/rivergate-citylight",
        "vendor: rivergate. Public post: loud for sale, ship from citylight, Surat. In stock.",
        6,
    ),
    (
        SourceClass.TOR_MARKET,
        "demo://surat/stationbook-rander",
        "vendor: stationbook. Observed listing: meth for sale, ship from rander, Surat. 3 grams. Wholesale.",
        8,
    ),
    (
        SourceClass.SURFACE_MARKET,
        "demo://surat/westlane-pal",
        "vendor: westlane. Observed listing: hash for sale, ship from pal, Surat. 4 grams.",
        10,
    ),
    (
        SourceClass.TELEGRAM,
        "demo://surat/rivergate-dumas",
        "vendor: rivergate. Channel note: pills for sale, ship from dumas, Surat. Bulk discount.",
        12,
    ),
    (
        SourceClass.TOR_FORUM,
        "demo://surat/stationbook-ringroad",
        "vendor: stationbook. Forum post: crystal for sale, ship from ringroad, Surat. Great vendor.",
        14,
    ),
]


async def _wait_for_intel(mongo, expected: int) -> int:
    for _ in range(90):
        count = await mongo.intel.count_documents({})
        if count >= expected:
            return count
        await asyncio.sleep(2)
    return await mongo.intel.count_documents({})


async def main() -> None:
    settings = get_settings()
    metrics = IngestionMetrics()
    pipeline, publisher, dedup_store, mongo = _pipeline_resources(
        settings,
        False,
        Path(settings.collection.contract_path),
        Path(settings.collection.safety_policy_path),
        metrics,
    )
    if mongo is None:
        raise RuntimeError("demo seed requires MongoDB")
    now = datetime.now(UTC)
    published = 0
    try:
        await mongo.connect()
        await mongo.watchlists.update_one(
            {"_id": "demo-surat-street"},
            {
                "$setOnInsert": {
                    "name": "Surat street names",
                    "terms": ["snow", "ice", "molly", "maal"],
                    "notify": True,
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        await publisher.start()
        for source_class, source_ref, text, days_ago in OBSERVATIONS:
            captured = now - timedelta(days=days_ago, hours=3)
            outcome = await pipeline.process(
                SourceRecord(
                    source_class=source_class,
                    source_ref=source_ref,
                    content_type=ContentType.TEXT,
                    mime_type="text/plain",
                    raw_content=text,
                    source_bytes=text.encode(),
                    captured_at=captured,
                    source_observed_at=captured,
                    lang_hint="en",
                    geo_hints=("surat",),
                )
            )
            if outcome.status.value == "published":
                published += 1
        for term, meaning in (("white pearl", "suspected cocaine nickname"), ("blue drop", "suspected MDMA tablet")):
            await mongo.slang.update_one(
                {"_id": f"en:{term}"},
                {
                    "$setOnInsert": {
                        "term": term,
                        "meaning": meaning,
                        "lang": "en",
                        "confidence": 0.42,
                        "newly_discovered": True,
                        "review_status": "pending",
                        "source": "demo",
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )
        await mongo.collection_runs.update_one(
            {"source_id": "demo-surat-corpus"},
            {
                "$set": {
                    "started_at": now - timedelta(minutes=20),
                    "finished_at": now,
                    "published": published or len(OBSERVATIONS),
                    "duplicates": 0,
                    "rejected": 0,
                    "failures": 0,
                    "failure_code": None,
                    "skipped": False,
                }
            },
            upsert=True,
        )
        await mongo.audit.update_one(
            {"_id": "demo-seed-audit"},
            {
                "$setOnInsert": {
                    "occurred_at": now,
                    "actor": "demo-seed",
                    "role": "administrator",
                    "action": "demo.corpus.seed",
                    "target_type": "intel",
                    "target_id": "demo-surat",
                    "path": "/demo/seed",
                    "method": "CLI",
                    "ip": "127.0.0.1",
                }
            },
            upsert=True,
        )
        from darkpulse.evidence.sealing import EvidenceSealer

        await EvidenceSealer().seal(b"DarkPulse demonstration corpus", mongo)
        intel_count = await _wait_for_intel(mongo, 8)
    finally:
        await publisher.stop()
        await dedup_store.close()
        await mongo.close()
    print(json.dumps({"published": published, "intel": intel_count}))


if __name__ == "__main__":
    asyncio.run(main())
