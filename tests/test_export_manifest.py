"""Export manifest (03.8) and GET-must-not-seal (03.16)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings
from darkpulse.config import Settings

mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock()
mock_mongo.raw_ingest.find = MagicMock()
mock_mongo.evidence.find_one = AsyncMock(return_value=None)
mock_mongo.export_manifests = AsyncMock()
mock_settings = Settings()


@pytest.fixture
def export_client(auth_settings, auth_headers):
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as c:
        c.headers.update(auth_headers)
        yield c
    app.dependency_overrides.clear()


def _intel_cursor(*docs: dict) -> AsyncMock:
    cursor = AsyncMock()
    cursor.to_list.return_value = list(docs)
    return cursor


def _empty_raw_cursor() -> MagicMock:
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    return cursor


_DOC = {
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


def test_post_export_writes_manifest_with_intel_ids(export_client: TestClient) -> None:
    mock_mongo.intel.find.return_value = _intel_cursor(_DOC)
    mock_mongo.raw_ingest.find.return_value = _empty_raw_cursor()
    mock_mongo.evidence.insert_one = AsyncMock()
    mock_mongo.export_manifests.insert_one = AsyncMock()
    mock_mongo.export_manifests.update_one = AsyncMock()

    response = export_client.post("/api/v1/export?format=json&intel_ids=intel-1")
    assert response.status_code == 200
    seal = response.headers["X-DarkPulse-Evidence-Seal"]

    mock_mongo.export_manifests.update_one.assert_awaited_once()
    written = mock_mongo.export_manifests.update_one.await_args.args[1]["$setOnInsert"]
    assert written["hash_sha256"] == seal
    assert written["intel_ids"] == ["intel-1"]


def test_get_export_rejected(export_client: TestClient) -> None:
    response = export_client.get("/api/v1/export?format=csv")
    assert response.status_code == 405


def test_manifest_lookup(export_client: TestClient) -> None:
    mock_mongo.export_manifests.find_one = AsyncMock(
        return_value={"hash_sha256": "a" * 64, "intel_ids": ["intel-1"], "format": "csv"}
    )
    response = export_client.get(f"/api/v1/export/manifest/{'a' * 64}")
    assert response.status_code == 200
    assert response.json()["data"]["intel_ids"] == ["intel-1"]

    mock_mongo.export_manifests.find_one = AsyncMock(return_value=None)
    response = export_client.get(f"/api/v1/export/manifest/{'a' * 64}")
    assert response.status_code == 404
