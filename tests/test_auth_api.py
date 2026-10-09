# ruff: noqa: S101

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_neo4j, get_settings
from darkpulse.api.security import Principal, mint_session
from darkpulse.config import Settings

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

VIEWER = mint_session(Principal(subject="viewer-1", role="viewer"), "viewer-token")
ANALYST = mint_session(Principal(subject="analyst-1", role="analyst"), "analyst-token")
ADMIN = mint_session(Principal(subject="admin-1", role="administrator"), "admin-token")

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
        response = client.get("/api/v1/intel", headers={"Authorization": f"Bearer {VIEWER}"})
    assert response.status_code == 200

def test_viewer_token_denied_on_analyst_endpoint() -> None:
    with _client() as client:
        response = client.put(
            "/api/v1/alerts/config",
            headers={"Authorization": f"Bearer {VIEWER}"},
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
            "/api/v1/operations/audit", headers={"Authorization": f"Bearer {ADMIN}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["minimized"] is True

def test_validation_error_uses_error_envelope_with_trace_id() -> None:
    with _client() as client:
        response = client.get(
            "/api/v1/intel?severity_min=999", headers={"Authorization": f"Bearer {VIEWER}"}
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
        response = client.get("/api/v1/intel", headers={"Authorization": f"Bearer {VIEWER}"})
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
            "/api/v1/intel?limit=1", headers={"Authorization": f"Bearer {VIEWER}"}
        )
        cursor = response.json()["pagination"]["cursor"]
        assert cursor == "2024-01-01T00:00:09Z|intel-9"

def test_health_degraded_reflects_services() -> None:
    mock_mongo.health = AsyncMock(return_value={"status": "healthy"})
    mock_neo4j.health = AsyncMock(return_value={"status": "red"})
    app.state.processor = MagicMock(healthy=True)
    with _client() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"

def test_evidence_verify_payload_endpoint() -> None:
    import hashlib

    payload = "case note"
    payload_hash = hashlib.sha256(payload.encode()).hexdigest()
    mock_mongo.evidence.find_one = AsyncMock(return_value=None)
    with _client() as client:
        response = client.post(
            "/api/v1/evidence/verify",
            headers={"Authorization": f"Bearer {VIEWER}"},
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
    settings.auth.local_open_mode = False
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
    settings.auth.local_open_mode = False
    settings.auth.tokens_json = __import__("pydantic").SecretStr(
        '{"0123456789abcdef0123456789abcdef": {"subject": "a", "role": "administrator"}}'
    )
    settings.neo4j.password = "darkpulse_dev"
    with (
        patch("darkpulse.api.app.get_settings", return_value=settings),
        pytest.raises(RuntimeError, match="NEO4J_PASSWORD"),
    ):
        async with lifespan(app):
            pass

def test_session_and_ticket_survive_a_cleared_local_cache() -> None:
    from darkpulse.api import security

    class Store:
        def __init__(self) -> None:
            self.data: dict[str, str] = {}

        def setex(self, key: str, _ttl: int, value: str) -> None:
            self.data[key] = value

        def get(self, key: str) -> str | None:
            return self.data.get(key)

        def delete(self, key: str) -> None:
            self.data.pop(key, None)

        def getdel(self, key: str) -> str | None:
            return self.data.pop(key, None)

    security._redis_disabled = False
    security._redis = Store()
    try:
        settings = _auth_settings()
        raw = security.mint_session(Principal(subject="viewer-1", role="viewer"), "viewer-token")
        security._sessions.pop(security._digest(raw), None)
        found = security.principal_from_session(raw, settings)
        assert found is not None
        assert found.subject == "viewer-1"
        security.revoke_session(raw)
        assert security.principal_from_session(raw, settings) is None
        ticket = security.mint_ticket(Principal(subject="viewer-1", role="viewer"))
        security._tickets.pop(security._digest(ticket), None)
        consumed = security.consume_ticket(ticket)
        assert consumed is not None
        assert consumed.subject == "viewer-1"
        assert security.consume_ticket(ticket) is None
    finally:
        security._redis = None
        security._redis_disabled = True

def test_session_dies_when_source_token_is_removed() -> None:
    from darkpulse.api.security import Principal, mint_session, principal_from_session

    settings = _auth_settings()
    raw = mint_session(Principal(subject="viewer-1", role="viewer"), "viewer-token")
    assert principal_from_session(raw, settings) is not None
    settings.auth.tokens_json = __import__("pydantic").SecretStr(
        '{"analyst-token": {"subject": "analyst-1", "role": "analyst"}}'
    )
    assert principal_from_session(raw, settings) is None

def test_viewer_payload_drops_identifiers() -> None:
    from darkpulse.api.serializers import serialize_intel

    doc = {
        "intel_id": "i-1",
        "translated_text": "pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa or call 9876543210",
        "entities": {"crypto_wallets": [{"address": "x"}], "vendors": []},
        "actor_links": [{"from": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "to": "i-2"}],
    }
    viewer = serialize_intel(doc, role="viewer")
    assert viewer["actor_links"] == []
    assert "crypto_wallets" not in viewer["entities"]
    assert "1A1zP1" not in viewer["translated_text"]
    assert "9876543210" not in viewer["translated_text"]
    analyst = serialize_intel(doc, role="analyst")
    assert analyst["actor_links"]
