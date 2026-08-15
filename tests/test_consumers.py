from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from darkpulse.broker.processor import MongoProcessor
from darkpulse.config import Settings


def raw_doc_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "ingest_id": "123e4567-e89b-12d3-a456-426614174000",
        "trace_id": "123e4567-e89b-12d3-a456-426614174000",
        "dedup_key": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "source_class": "tor_market",
        "source_ref": "http://example.onion",
        "content_type": "text",
        "raw_content": "buy mdma",
        "captured_at": "2024-01-01T12:00:00Z",
        "evidence": {
            "hash_algorithm": "sha256",
            "source_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "source_size_bytes": 100,
            "content_size_bytes": 100,
            "captured_at": "2024-01-01T12:00:00Z",
            "collector_id": "test",
            "collector_version": "1.0",
        },
        "safety": {
            "status": "accepted",
            "policy_version": "1.0",
            "checks": ["size", "type"],
            "binary_content_stored": False,
        },
    }


def claimed_doc() -> dict:
    doc = raw_doc_payload()
    doc["processing"] = {"status": "processing", "attempts": 1}
    return doc


@pytest.fixture
def processor():
    settings = Settings()
    return MongoProcessor(settings, AsyncMock(), AsyncMock())


@pytest.mark.asyncio
async def test_process_doc_success(processor):
    processor._refresh_pipeline = AsyncMock()
    processor._nlp_pipeline = MagicMock()
    processor._nlp_pipeline.process.return_value = None
    processor.mongo.raw_ingest.update_one = AsyncMock()
    await processor._process_doc(claimed_doc())
    terminal_update = processor.mongo.raw_ingest.update_one.await_args_list[-1].args[1]["$set"]
    assert terminal_update["processing.status"] == "dropped"


@pytest.mark.asyncio
async def test_process_doc_failure_marks_failed(processor):
    processor._refresh_pipeline = AsyncMock()
    processor._nlp_pipeline = MagicMock()
    processor._nlp_pipeline.process.side_effect = RuntimeError("temporary NLP failure")
    processor.mongo.raw_ingest.update_one = AsyncMock()
    with pytest.raises(RuntimeError, match="temporary NLP failure"):
        await processor._process_doc(claimed_doc())
    failed_update = processor.mongo.raw_ingest.update_one.await_args_list[-1].args[1]["$set"]
    assert failed_update["processing.status"] == "failed"
    assert failed_update["processing.last_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_process_doc_exhausted_after_max_attempts(processor):
    processor._refresh_pipeline = AsyncMock()
    processor._nlp_pipeline = MagicMock()
    processor._nlp_pipeline.process.side_effect = RuntimeError("permanent failure")
    processor.mongo.raw_ingest.update_one = AsyncMock()
    doc = claimed_doc()
    doc["processing"]["attempts"] = processor.settings.processor.max_attempts
    with pytest.raises(RuntimeError):
        await processor._process_doc(doc)
    failed_update = processor.mongo.raw_ingest.update_one.await_args_list[-1].args[1]["$set"]
    assert failed_update["processing.status"] == "exhausted"


@pytest.mark.asyncio
async def test_process_doc_accepts_naive_mongo_datetimes(processor):
    from datetime import UTC, datetime

    processor._refresh_pipeline = AsyncMock()
    processor._nlp_pipeline = MagicMock()
    processor._nlp_pipeline.process.return_value = None
    processor.mongo.raw_ingest.update_one = AsyncMock()
    doc = claimed_doc()
    doc["captured_at"] = datetime(2024, 1, 1, 12, 0, 0)
    doc["source_observed_at"] = datetime(2024, 1, 1, 12, 0, 0)
    doc["evidence"]["captured_at"] = datetime(2024, 1, 1, 12, 0, 0)
    await processor._process_doc(doc)
    captured = processor._nlp_pipeline.process.call_args.args[0]
    assert captured.captured_at.tzinfo is UTC
    assert captured.evidence.captured_at.tzinfo is UTC


@pytest.mark.asyncio
async def test_claim_next_uses_lease_and_attempts(processor):
    processor.mongo.raw_ingest.find_one_and_update = AsyncMock(return_value=None)
    result = await processor._claim_next()
    assert result is None
    claimed = processor.mongo.raw_ingest.find_one_and_update.await_args
    assert claimed.kwargs["return_document"] is not None
    assert "$inc" in claimed.args[1]


@pytest.mark.asyncio
async def test_watchlist_alerts_work_without_threshold_config(processor):
    processor.mongo.alerts_config.find_one = AsyncMock(return_value=None)
    watch_cursor = MagicMock()
    watch_cursor.to_list = AsyncMock(
        return_value=[
            {"_id": "watch-1", "name": "MDMA", "terms": ["mdma"], "enabled": True, "notify": True}
        ]
    )
    processor.mongo.watchlists.find = MagicMock(return_value=watch_cursor)
    processor.mongo.alerts_history.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="alert-1")
    )
    record = MagicMock(products=[], geo=None, severity=MagicMock(score=75), intel_id="intel-1")
    await processor._evaluate_alerts(
        record, {"translated_text": "MDMA available", "products": [], "slang_decoded": []}
    )
    processor.mongo.alerts_history.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_intel_success(processor):
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

    processor.mongo.intel.insert_one = AsyncMock()
    processor.mongo.alerts_config.find_one = AsyncMock(return_value=None)
    watch_cursor = MagicMock()
    watch_cursor.to_list = AsyncMock(return_value=[])
    processor.mongo.watchlists.find = MagicMock(return_value=watch_cursor)

    await processor._process_intel(payload)
    processor.mongo.intel.insert_one.assert_called_once()
    processor.neo4j.upsert_intel_graph.assert_called_once()


@pytest.mark.asyncio
async def test_process_intel_replay_is_idempotent(processor):
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

    processor.mongo.intel.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))
    processor.mongo.alerts_config.find_one = AsyncMock(return_value=None)

    await processor._process_intel(payload)
    processor.neo4j.upsert_intel_graph.assert_called_once()
