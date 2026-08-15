from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_neo4j, get_settings
from darkpulse.api.excerpts import normalize_excerpt
from darkpulse.api.serializers import flatten_canonicals, serialize_intel
from darkpulse.config import Neo4jSettings, Settings
from darkpulse.storage.neo4j import Neo4jManager

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock()
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
    mock_neo4j.reset_mock()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _client() -> TestClient:
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_neo4j] = lambda: mock_neo4j
    app.dependency_overrides[get_settings] = _auth_settings
    return TestClient(app)


def test_flatten_canonicals_unnests_product_arrays() -> None:
    assert flatten_canonicals([["mdma"], {"canonical": "heroin"}, "mdma", None]) == [
        "mdma",
        "heroin",
    ]


def test_serialize_intel_strips_mongo_id() -> None:
    payload = serialize_intel(
        {
            "_id": "mongo-internal",
            "intel_id": "intel-1",
            "ingest_id": "ingest-1",
            "captured_at": "2024-01-01T00:00:00Z",
            "processing": {"status": "done"},
        }
    )
    assert "_id" not in payload
    assert "processing" not in payload
    assert payload["intel_id"] == "intel-1"


def test_normalize_excerpt_never_returns_raw_json() -> None:
    excerpt = normalize_excerpt('{"title": "Surat NDPS seizure", "url": "https://example.invalid"}')
    assert "{" not in excerpt
    assert "Surat NDPS seizure" in excerpt


def test_graph_stable_ids_and_center_resolution() -> None:
    manager = Neo4jManager(Neo4jSettings())
    assert manager._stable_id("Vendor", {"alias": "alice"}) == "vendor:alice"
    assert manager._stable_id("IntelRef", {"intel_id": "intel-9"}) == "intel:intel-9"
    assert manager._resolve_center("intel:intel-9", "Vendor") == ("IntelRef", "intel-9")
    assert manager._resolve_center("alice", "Vendor") == ("Vendor", "alice")
    assert manager._resolve_center("neighborhood:Adajan", "Vendor") == ("Neighborhood", "Adajan")


@pytest.mark.asyncio
async def test_graph_returns_empty_when_driver_missing() -> None:
    manager = Neo4jManager(Neo4jSettings())
    graph = await manager.get_subgraph(center="intel:missing")
    assert graph == {
        "nodes": [],
        "edges": [],
        "truncated": False,
        "limits": {"max_nodes": 200},
    }


def test_auth_login_and_me() -> None:
    with _client() as client:
        denied = client.post("/api/v1/auth/login", json={"token": "wrong"})
        assert denied.status_code == 401
        accepted = client.post("/api/v1/auth/login", json={"token": "analyst-token"})
        assert accepted.status_code == 200
        assert accepted.json()["data"] == {
            "subject": "analyst-1",
            "role": "analyst",
            "token": "analyst-token",
        }
        me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer viewer-token"})
        assert me.status_code == 200
        assert me.json()["data"] == {"subject": "viewer-1", "role": "viewer"}


def test_search_accepts_hinglish() -> None:
    mock_mongo.search_intel = AsyncMock(return_value={"total": 0, "records": []})
    with _client() as client:
        response = client.get(
            "/api/v1/search?q=maal&lang=hinglish",
            headers={"Authorization": "Bearer viewer-token"},
        )
    assert response.status_code == 200
    mock_mongo.search_intel.assert_awaited()
    assert mock_mongo.search_intel.await_args.kwargs["lang"] == "hinglish"


def test_watchlist_match_count_from_alerts() -> None:
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(
        return_value=[
            {
                "_id": "wl-1",
                "name": "Opioids",
                "terms": ["fentanyl"],
                "notify": True,
                "enabled": True,
            }
        ]
    )
    mock_mongo.watchlists.find = MagicMock(return_value=cursor)
    grouped = MagicMock()
    grouped.to_list = AsyncMock(return_value=[{"_id": "wl-1", "count": 4}])
    mock_mongo.alerts_history.aggregate = MagicMock(return_value=grouped)
    with _client() as client:
        response = client.get(
            "/api/v1/watchlists",
            headers={"Authorization": "Bearer viewer-token"},
        )
    assert response.status_code == 200
    assert response.json()["data"][0]["match_count"] == 4
