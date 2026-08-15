from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from darkpulse.models import (
    ActorLink,
    ActorRelation,
    IntelSummary,
    RawIngest,
    SeverityBand,
    TraffickingIntel,
)


def test_intel_summary_model():
    summary = IntelSummary(
        intel_id="id-1",
        ingest_id="id-in-1",
        captured_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        intent_label="sale",
        severity_score=85.0,
        severity_band="high",
    )
    assert summary.intel_id == "id-1"
    assert summary.severity_band == "high"


def test_contract1_validation():
    payload = {
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

    record = RawIngest.model_validate(payload)
    assert str(record.ingest_id) == payload["ingest_id"]


def test_contract2_validation():
    payload = {
        "intel_id": "123e4567-e89b-12d3-a456-426614174001",
        "ingest_id": "123e4567-e89b-12d3-a456-426614174000",
        "captured_at": "2024-01-01T12:00:00Z",
        "sanitization": {"status": "clean"},
        "intent": {"label": "sale", "score": 0.95},
        "severity": {"score": 85.5, "band": "high"},
        "confidence": 90.0,
        "actor_links": [
            {"from": "VendorA", "to": "VendorB", "relation": "same_as", "confidence": 0.8}
        ],
    }

    record = TraffickingIntel.model_validate(payload)
    assert record.severity.band == SeverityBand.HIGH
    assert len(record.actor_links) == 1
    assert record.actor_links[0].from_actor == "VendorA"


def test_actor_link_wire_format():
    link = ActorLink(from_actor="A", to_actor="B", relation=ActorRelation.SAME_AS, confidence=0.9)
    dumped = link.model_dump(by_alias=True)
    assert dumped["from"] == "A"
    assert dumped["to"] == "B"
    assert "from_actor" not in dumped


def test_invalid_contract_rejected():
    with pytest.raises(ValidationError):
        TraffickingIntel.model_validate({"intel_id": "123e4567-e89b-12d3-a456-426614174001"})
