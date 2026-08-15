# ruff: noqa: S101

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_neo4j, get_settings
from darkpulse.config import Settings

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock()
mock_mongo.evidence.find = MagicMock()
mock_neo4j = AsyncMock()


def _auth_settings() -> Settings:
    settings = Settings()
    settings.auth.enabled = True
    settings.auth.tokens_json = __import__("pydantic").SecretStr(
        '{"analyst-token": {"subject": "analyst-1", "role": "analyst"},'
        '"viewer-token": {"subject": "viewer-1", "role": "viewer"},'
        '"admin-token": {"subject": "admin-1", "role": "administrator"}}'
    )
    return settings


@pytest.fixture(autouse=True)
def _reset_mocks():
    mock_mongo.reset_mock()
    mock_mongo.intel.find = MagicMock()
    mock_mongo.evidence.find = MagicMock()
    mock_neo4j.reset_mock()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _client() -> TestClient:
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_neo4j] = lambda: mock_neo4j
    app.dependency_overrides[get_settings] = _auth_settings
    return TestClient(app)


def test_missing_token_returns_401_with_envelope() -> None:
    with _client() as client:
        response = client.get("/api/v1/intel")
    assert response.status_code == 401
    body = response.json()
    assert body["data"] is None
    assert body["errors"][0]["code"] == "unauthenticated"


def test_invalid_token_returns_401() -> None:
    with _client() as client:
        response = client.get("/api/v1/intel", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_viewer_token_grants_read() -> None:
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = []
    mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = mock_cursor
    mock_mongo.intel.count_documents = AsyncMock(return_value=0)
    with _client() as client:
        response = client.get("/api/v1/intel", headers={"Authorization": "Bearer viewer-token"})
    assert response.status_code == 200


def test_viewer_token_denied_on_analyst_endpoint() -> None:
    with _client() as client:
        response = client.put(
            "/api/v1/alerts/config",
            headers={"Authorization": "Bearer viewer-token"},
            json={"rules": []},
        )
    assert response.status_code == 403


def test_admin_token_can_read_operations() -> None:
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_mongo.audit.find = MagicMock(return_value=mock_cursor)
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    with _client() as client:
        response = client.get(
            "/api/v1/operations/audit", headers={"Authorization": "Bearer admin-token"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["minimized"] is True


def test_validation_error_uses_error_envelope_with_trace_id() -> None:
    with _client() as client:
        response = client.get(
            "/api/v1/intel?severity_min=999", headers={"Authorization": "Bearer viewer-token"}
        )
    assert response.status_code == 422
    body = response.json()
    assert body["data"] is None
    assert body["errors"]
    assert body["errors"][0]["code"] == "request_validation_failed"


def test_intel_pagination_cursor_only_when_more_pages() -> None:
    def _docs(limit: int):
        mock_cursor = AsyncMock()
        mock_cursor.to_list.return_value = [
            {
                "intel_id": f"intel-{index}",
                "ingest_id": f"ingest-{index}",
                "captured_at": f"2024-01-01T00:00:0{index}Z",
                "intent": {"label": "sale", "score": 0.9},
                "severity": {"band": "high", "score": 80.0},
            }
            for index in range(limit)
        ]
        mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = mock_cursor
        return mock_cursor

    with _client() as client:
        _docs(1)
        mock_mongo.intel.count_documents = AsyncMock(return_value=1)
        response = client.get("/api/v1/intel", headers={"Authorization": "Bearer viewer-token"})
        assert response.status_code == 200
        assert response.json()["pagination"]["cursor"] is None

        mock_mongo.intel.find.reset_mock()
        mock_mongo.intel.find = MagicMock()
        cursor_mock = AsyncMock()
        docs = [
            {
                "intel_id": "intel-9",
                "ingest_id": "ingest-9",
                "captured_at": "2024-01-01T00:00:09Z",
                "intent": {"label": "sale", "score": 0.9},
                "severity": {"band": "high", "score": 80.0},
            },
            {
                "intel_id": "intel-8",
                "ingest_id": "ingest-8",
                "captured_at": "2024-01-01T00:00:08Z",
                "intent": {"label": "sale", "score": 0.9},
                "severity": {"band": "high", "score": 80.0},
            },
        ]
        cursor_mock.to_list.return_value = docs
        mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = cursor_mock
        mock_mongo.intel.count_documents = AsyncMock(return_value=3)
        response = client.get(
            "/api/v1/intel?limit=1", headers={"Authorization": "Bearer viewer-token"}
        )
        cursor = response.json()["pagination"]["cursor"]
        assert cursor == "2024-01-01T00:00:09Z|intel-9"


def test_health_degraded_reflects_services() -> None:
    mock_mongo.health = AsyncMock(return_value={"status": "healthy"})
    mock_neo4j.health = AsyncMock(return_value={"status": "red"})
    app.state.processor = MagicMock(healthy=True)
    with _client() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_evidence_verify_payload_endpoint() -> None:
    import hashlib

    payload = "case note"
    payload_hash = hashlib.sha256(payload.encode()).hexdigest()
    mock_mongo.evidence.find_one = AsyncMock(return_value=None)
    with _client() as client:
        response = client.post(
            "/api/v1/evidence/verify",
            headers={"Authorization": "Bearer viewer-token"},
            json={"payload": payload, "hash_sha256": payload_hash},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["matches"] is True
    assert body["data"]["ledger_recorded"] is False


@pytest.mark.asyncio
async def test_production_requires_auth_and_real_credentials() -> None:
    from darkpulse.api.app import lifespan

    settings = Settings()
    settings.service.environment = "production"
    settings.auth.enabled = False
    settings.auth.tokens_json = None
    with (
        patch("darkpulse.api.app.get_settings", return_value=settings),
        pytest.raises(RuntimeError, match="DARKPULSE_AUTH_ENABLED"),
    ):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_production_rejects_default_neo4j_password() -> None:
    from darkpulse.api.app import lifespan

    settings = Settings()
    settings.service.environment = "production"
    settings.auth.enabled = True
    settings.auth.tokens_json = __import__("pydantic").SecretStr(
        '{"token": {"subject": "a", "role": "administrator"}}'
    )
    settings.neo4j.password = "darkpulse_dev"
    with (
        patch("darkpulse.api.app.get_settings", return_value=settings),
        pytest.raises(RuntimeError, match="NEO4J_PASSWORD"),
    ):
        async with lifespan(app):
            pass
