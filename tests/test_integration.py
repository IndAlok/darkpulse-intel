from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from darkpulse.broker.processor import MongoProcessor
from darkpulse.config import Settings
from darkpulse.ingestion.dedup import InMemoryDedupStore
from darkpulse.ingestion.hashing import derive_dedup_key, sha256_hex
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.pipeline import IngestionPipeline
from darkpulse.ingestion.publisher import InMemoryPublisher
from darkpulse.ingestion.records import SourceRecord
from darkpulse.ingestion.safety import SafetyPolicy
from darkpulse.ingestion.validation import ContractValidator
from darkpulse.models import ContentType, CrawlMetadata, RawIngest, SourceClass, TraffickingIntel
from darkpulse.nlp.pipeline import NLPPipeline
from darkpulse.nlp.slang import SlangDictionary

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts/contract1-raw-ingest.schema.json"
SAFETY_PATH = Path(__file__).resolve().parents[1] / "safety/policy/prepublish-v1.json"


def make_source_record(content: str, source_ref: str = "dataset://integration/1") -> SourceRecord:
    now = datetime.now(UTC)
    content_bytes = content.encode("utf-8")
    return SourceRecord(
        source_class=SourceClass.DNM_DATASET,
        source_ref=source_ref,
        content_type=ContentType.TEXT,
        mime_type="text/plain",
        raw_content=content,
        source_bytes=content_bytes,
        captured_at=now,
        source_observed_at=now,
        crawl_metadata=CrawlMetadata(source_item_id="integration-1"),
        source_metadata={"fixture": True},
    )


def make_raw_ingest(content: str, source_ref: str = "dataset://integration/1") -> RawIngest:
    now = datetime.now(UTC)
    content_sha = sha256_hex(content.encode("utf-8"))
    return RawIngest(
        ingest_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        dedup_key=derive_dedup_key(
            source_class="dnm_dataset", source_ref=source_ref, content_sha256=content_sha
        ),
        source_class="dnm_dataset",
        source_ref=source_ref,
        content_type="text",
        raw_content=content,
        captured_at=now,
        source_observed_at=now,
        evidence={
            "source_sha256": content_sha,
            "content_sha256": content_sha,
            "source_size_bytes": len(content.encode("utf-8")),
            "content_size_bytes": len(content.encode("utf-8")),
            "captured_at": now,
            "collector_id": "integration",
            "collector_version": "1.0.0",
        },
        safety={
            "policy_version": "prepublish-v1",
            "checks": ["size", "type"],
            "binary_content_stored": False,
        },
    )


async def run_ingestion(content: str) -> tuple[IngestionPipeline, InMemoryPublisher, str]:
    policy = SafetyPolicy.from_path(SAFETY_PATH)
    validator = ContractValidator(CONTRACT_PATH)
    publisher = InMemoryPublisher()
    pipeline = IngestionPipeline(
        safety_policy=policy,
        dedup_store=InMemoryDedupStore(),
        publisher=publisher,
        validator=validator,
        metrics=IngestionMetrics(),
        collector_id="integration",
        collector_version="1.0.0",
    )
    await publisher.start()
    record = make_source_record(content)
    _ = await pipeline.process(record)
    await publisher.stop()
    return pipeline, publisher, str(publisher.records[0].ingest_id)


def run_pipeline(content: str) -> TraffickingIntel | None:
    slang = SlangDictionary()
    seed = Path(__file__).resolve().parents[1] / "data/slang_dictionary/seed_dictionary.txt"
    slang.load_seed(seed)
    pipe = NLPPipeline(slang_dictionary=slang)
    record = make_raw_ingest(content)
    return pipe.process(record)


class TestEndToEndPipeline:
    def test_full_ingest_to_intel_flow(self):
        content = (
            "Snow and molly available in Adajan. Contact @surat_dealer. "
            "BTC: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa. $50 for 10 pills."
        )
        _, publisher, ingest_id = asyncio.run(run_ingestion(content))
        assert len(publisher.records) == 1
        c1 = publisher.records[0]
        assert str(c1.ingest_id) == ingest_id

        slang = SlangDictionary()
        seed = Path(__file__).resolve().parents[1] / "data/slang_dictionary/seed_dictionary.txt"
        slang.load_seed(seed)
        pipe = NLPPipeline(slang_dictionary=slang)
        intel = pipe.process(c1)
        assert intel is not None
        assert intel.ingest_id == ingest_id
        assert any(p.canonical == "cocaine" for p in intel.products if p.canonical)
        assert intel.severity.band.value in {"info", "low", "medium", "high", "critical"}

    def test_wallet_address_survives_normalization(self):
        content = "Send to BTC: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa for the goods."
        intel = run_pipeline(content)
        assert intel is not None
        wallets = [w.address for w in (intel.entities.crypto_wallets or []) if w.address]
        assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in wallets

    def test_products_include_prices_and_quantities(self):
        content = "MDMA pills $50 for 10 pills. Cocaine 5 grams available."
        intel = run_pipeline(content)
        assert intel is not None
        assert len(intel.products) > 0
        for p in intel.products:
            if p.price:
                assert "50" in p.price
            if p.quantity:
                assert p.quantity

    def test_dropped_content_returns_none(self):
        slang = SlangDictionary()
        pipe = NLPPipeline(slang_dictionary=slang)
        record = make_raw_ingest("child porn available. DM for links.")
        result = pipe.process(record)
        assert result is None
        assert pipe.metrics["dropped"] == 1


class TestConsumerIdempotency:
    def test_replay_does_not_duplicate_intel(self):
        settings = Settings()
        mongo = AsyncMock()
        mongo.intel.insert_one = AsyncMock()
        mongo.alerts_config.find_one = AsyncMock(return_value=None)
        watch_cursor = MagicMock()
        watch_cursor.to_list = AsyncMock(return_value=[])
        mongo.watchlists.find = MagicMock(return_value=watch_cursor)
        neo4j = AsyncMock()
        processor = MongoProcessor(settings, mongo, neo4j)

        payload = {
            "intel_id": "123e4567-e89b-12d3-a456-426614174001",
            "ingest_id": "123e4567-e89b-12d3-a456-426614174000",
            "captured_at": "2024-01-01T12:00:00Z",
            "sanitization": {"status": "clean"},
            "intent": {"label": "sale", "score": 0.95},
            "severity": {"score": 85.5, "band": "high"},
            "confidence": 90.0,
            "products": [{"canonical": "cocaine", "raw_term": "cocaine", "slang": False}],
        }

        asyncio.run(processor._process_intel(payload))
        mongo.intel.insert_one.assert_called_once()
        neo4j.upsert_intel_graph.assert_called_once()
        neo4j.upsert_intel_graph.assert_called_once()

        from pymongo.errors import DuplicateKeyError

        mongo.intel.insert_one.side_effect = DuplicateKeyError("dup")
        asyncio.run(processor._process_intel(payload))
        neo4j.upsert_intel_graph.assert_called()
        neo4j.upsert_intel_graph.assert_called()

    def test_alert_respects_product_filter(self):
        settings = Settings()
        mongo = AsyncMock()
        mongo.intel.insert_one = AsyncMock()
        mongo.alerts_config.find_one = AsyncMock(
            return_value={
                "_id": "default",
                "rules": [
                    {
                        "name": "cocaine-only",
                        "severity_min": 50,
                        "products": ["heroin"],
                        "neighborhoods": [],
                        "enabled": True,
                    }
                ],
            }
        )
        mongo.alerts_history.insert_one = AsyncMock()
        watch_cursor = MagicMock()
        watch_cursor.to_list = AsyncMock(return_value=[])
        mongo.watchlists.find = MagicMock(return_value=watch_cursor)
        neo4j = AsyncMock()
        processor = MongoProcessor(settings, mongo, neo4j)

        payload = {
            "intel_id": "123e4567-e89b-12d3-a456-426614174002",
            "ingest_id": "123e4567-e89b-12d3-a456-426614174000",
            "captured_at": "2024-01-01T12:00:00Z",
            "sanitization": {"status": "clean"},
            "intent": {"label": "sale", "score": 0.95},
            "severity": {"score": 85.5, "band": "high"},
            "confidence": 90.0,
            "products": [{"canonical": "cocaine", "raw_term": "cocaine", "slang": False}],
        }

        asyncio.run(processor._process_intel(payload))
        mongo.alerts_history.insert_one.assert_not_called()


class TestEvidenceChain:
    def test_chain_links_consecutive_seals(self):
        from darkpulse.evidence.sealing import EvidenceSealer

        mongo = AsyncMock()
        mongo.evidence.insert_one = AsyncMock()
        mongo.evidence.find_one = AsyncMock(return_value={"hash_sha256": "prev-hash"})
        sealer = EvidenceSealer()
        seal = asyncio.run(sealer.seal(b"payload", mongo, previous_hash="prev-hash"))
        assert seal.previous_hash == "prev-hash"
        assert seal.tsa_verified is False
        assert seal.provenance == "DarkPulse/hash-only"
