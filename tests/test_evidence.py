from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings
from darkpulse.config import Settings

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_settings = Settings()
mock_settings.evidence.rfc3161_enabled = False


@pytest.fixture
def evidence_client():
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_settings] = lambda: mock_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_seal_evidence(evidence_client: TestClient) -> None:
    mock_mongo.evidence.insert_one = AsyncMock()
    mock_mongo.evidence.find_one = AsyncMock(return_value=None)

    payload = {"payload": "This is a test payload for sealing."}
    response = evidence_client.post("/api/v1/evidence/seal", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "hash_sha256" in data["data"]
    assert data["data"]["provenance"] == "DarkPulse/hash-only"
    assert data["data"]["tsa_verified"] is False
    assert data["data"]["previous_hash"] is None
