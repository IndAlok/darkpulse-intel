from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from conftest import CONTRACT_PATH
from jsonschema import Draft202012Validator

from darkpulse.models import (
    SCHEMA_VERSION,
    Intent,
    Sanitization,
    Severity,
    SeverityBand,
    TraffickingIntel,
)


def test_contract_schema_is_valid_draft_2020_12() -> None:
    schema = json.loads(Path(CONTRACT_PATH).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION


def test_contract_requires_separate_source_and_content_hashes() -> None:
    schema = json.loads(Path(CONTRACT_PATH).read_text(encoding="utf-8"))
    required = schema["$defs"]["evidence"]["required"]
    assert "source_sha256" in required
    assert "content_sha256" in required
    assert "dedup_key" in schema["required"]


def test_synthetic_contract_example_validates() -> None:
    schema = json.loads(Path(CONTRACT_PATH).read_text(encoding="utf-8"))
    example_path = CONTRACT_PATH.parent / "examples/raw-ingest.example.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(example)


def test_contract2_wire_format_validates_against_schema() -> None:
    schema_path = CONTRACT_PATH.parent / "contract2-intel.schema.json"
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))

    intel = TraffickingIntel(
        intel_id="123e4567-e89b-12d3-a456-426614174001",
        ingest_id="123e4567-e89b-12d3-a456-426614174000",
        trace_id="123e4567-e89b-12d3-a456-426614174000",
        captured_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        sanitization=Sanitization(status="clean"),
        intent=Intent(label="sale", score=0.95),
        severity=Severity(score=85.5, band=SeverityBand.HIGH),
        confidence=90.0,
        products=[{"canonical": "cocaine", "raw_term": "cocaine", "slang": False}],
        actor_links=[
            {"from": "VendorA", "to": "VendorB", "relation": "same_as", "confidence": 0.8}
        ],
    )
    wire = json.loads(intel.model_dump_json(by_alias=True, exclude_none=True))
    Draft202012Validator(schema).validate(wire)
    assert wire["actor_links"][0]["from"] == "VendorA"
    assert "from_actor" not in wire["actor_links"][0]
