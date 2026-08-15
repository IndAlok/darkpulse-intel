import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings
from darkpulse.api.routes.export import _flatten_doc, _pdf_report
from darkpulse.config import Settings
from darkpulse.evidence.sealing import sha256_hex

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock()
mock_mongo.raw_ingest.find = MagicMock()
mock_settings = Settings()
mock_mongo.evidence.find_one = AsyncMock(return_value=None)


@pytest.fixture
def export_client():
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_settings] = lambda: mock_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _empty_raw_cursor() -> MagicMock:
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    return cursor


def test_export_csv(export_client: TestClient) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "intel_id": "intel-1",
            "ingest_id": "ingest-1",
            "captured_at": "2024-01-01T00:00:00Z",
            "severity": {"score": 85.0, "band": "high"},
            "intent": {"label": "sale", "score": 0.95},
            "products": [{"canonical": "cocaine"}],
            "geo": {"neighborhood": "adajan"},
            "source_class": "tor_market",
            "confidence": 90.0,
        }
    ]
    mock_mongo.intel.find.return_value = mock_cursor
    mock_mongo.raw_ingest.find.return_value = _empty_raw_cursor()
    mock_mongo.evidence.insert_one = AsyncMock()

    response = export_client.get("/api/v1/export?format=csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "intel-1" in response.text
    assert "85.0" in response.text
    assert "--- EVIDENCE SEAL ---" in response.text

    seal_hash = response.headers["X-DarkPulse-Evidence-Seal"]
    assert seal_hash
    data_bytes = response.content.split(b"--- EVIDENCE SEAL ---", 1)[0]
    assert sha256_hex(data_bytes) == seal_hash
    assert seal_hash in response.text


def test_export_json(export_client: TestClient) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {"intel_id": "intel-1", "severity": {"score": 85.0, "band": "high"}}
    ]
    mock_mongo.intel.find.return_value = mock_cursor
    mock_mongo.raw_ingest.find.return_value = _empty_raw_cursor()
    mock_mongo.evidence.insert_one = AsyncMock()

    response = export_client.get("/api/v1/export?format=json")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    data = response.json()
    assert "data" in data
    assert "evidence_seal" in data
    assert data["data"][0]["intel_id"] == "intel-1"

    canonical = json.dumps({"data": data["data"]}, default=str, separators=(",", ":")).encode()
    assert sha256_hex(canonical) == data["evidence_seal"]["hash_sha256"]
    assert response.headers["X-DarkPulse-Evidence-Seal"] == data["evidence_seal"]["hash_sha256"]


def test_pdf_manifest_uses_exact_canonical_bytes() -> None:
    record = {
        "intel_id": "intel-1",
        "severity_band": "high",
        "intent_label": "sale",
        "products": "cocaine",
        "neighborhood": "adajan",
    }
    content_pdf = _pdf_report([record])
    manifest = {
        "hash_sha256": sha256_hex(content_pdf),
        "sealed_at": 1,
        "provenance": "DarkPulse/hash-only",
        "previous_hash": None,
        "tsa_verified": False,
    }
    rendered = _pdf_report([record], manifest)
    assert rendered.startswith(b"%PDF")
    assert manifest["hash_sha256"].encode() in rendered


def test_flatten_doc_includes_provenance_fields() -> None:
    flat = _flatten_doc(
        {
            "intel_id": "intel-1",
            "trace_id": "trace-1",
            "content_hash": "abc",
            "evidence_ref": "ref-1",
            "slang_decoded": [{"term": "snow"}],
            "entities": {
                "vendors": [{"alias": "vendor-1"}],
                "crypto_wallets": [{"address": "addr-1"}],
                "contacts": [{"value_redacted": "+91...10"}],
            },
        },
        source_ref="dataset://x",
    )
    assert flat["trace_id"] == "trace-1"
    assert flat["content_hash"] == "abc"
    assert flat["evidence_ref"] == "ref-1"
    assert flat["source_ref"] == "dataset://x"
    assert flat["slang_decoded"] == "snow"
    assert flat["vendor_aliases"] == "vendor-1"
    assert flat["crypto_wallets"] == "addr-1"
