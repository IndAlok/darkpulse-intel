from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings
from darkpulse.api.routes.export import _csv_cell, _flatten_doc, _pdf_report
from darkpulse.config import Settings
from darkpulse.evidence.sealing import sha256_hex

mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock()
mock_mongo.raw_ingest.find = MagicMock()
mock_settings = Settings()
mock_mongo.evidence.find_one = AsyncMock(return_value=None)
mock_mongo.export_manifests = AsyncMock()

@pytest.fixture
def export_client(auth_settings, auth_headers):
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_settings] = lambda: mock_settings
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as c:
        c.headers.update(auth_headers)
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

    response = export_client.post("/api/v1/export?format=csv&intel_ids=intel-1")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "intel-1" in response.text
    assert "85.0" in response.text

    seal_hash = response.headers["X-DarkPulse-Evidence-Seal"]
    assert seal_hash
    assert sha256_hex(response.content) == seal_hash

def test_export_json(export_client: TestClient) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {"intel_id": "intel-1", "severity": {"score": 85.0, "band": "high"}}
    ]
    mock_mongo.intel.find.return_value = mock_cursor
    mock_mongo.raw_ingest.find.return_value = _empty_raw_cursor()
    mock_mongo.evidence.insert_one = AsyncMock()

    response = export_client.post("/api/v1/export?format=json&intel_ids=intel-1")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    data = response.json()
    assert "data" in data
    assert data["data"][0]["intel_id"] == "intel-1"
    assert sha256_hex(response.content) == response.headers["X-DarkPulse-Evidence-Seal"]

def test_pdf_manifest_uses_exact_canonical_bytes() -> None:
    record = {
        "intel_id": "intel-1",
        "severity_band": "high",
        "intent_label": "sale",
        "products": "cocaine",
        "neighborhood": "adajan",
    }
    record["vendor_aliases"] = "સુરત"
    rendered = _pdf_report([record])
    assert rendered.startswith(b"%PDF")

def test_csv_cells_cannot_start_formulas() -> None:
    assert _csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _csv_cell("cocaine") == "cocaine"
    assert _csv_cell(85.0) == 85.0

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
    assert flat["source_ref"] == "dataset://x"
    assert flat["slang_decoded"] == "snow"
    assert flat["vendor_aliases"] == "vendor-1"
    assert flat["crypto_wallets"] == "addr-1"
