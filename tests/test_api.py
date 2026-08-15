# ruff: noqa: S101

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_neo4j

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock()
mock_mongo.watchlists.find = MagicMock()
mock_mongo.slang.find = MagicMock()
mock_mongo.alerts_history.find = MagicMock()

mock_neo4j = AsyncMock()


@pytest.fixture
def api_client():
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_neo4j] = lambda: mock_neo4j
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_intel_list(api_client):
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "intel_id": "test-123",
            "ingest_id": "test-ingest",
            "captured_at": "2024-01-01T12:00:00Z",
            "intent": {"label": "sale", "score": 0.95},
            "severity": {"band": "high", "score": 85.0},
        }
    ]
    mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = mock_cursor
    mock_mongo.intel.count_documents.return_value = 1

    response = api_client.get("/api/v1/intel")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]) == 1
    assert data["data"][0]["intel_id"] == "test-123"
    assert "pagination" in data
    assert data["pagination"]["total"] == 1


def test_intel_detail(api_client):
    mock_mongo.intel.find_one.side_effect = None
    mock_mongo.intel.find_one.return_value = {
        "_id": "internal-mongo-id",
        "intel_id": "test-123",
        "trace_id": "trace-456",
    }

    response = api_client.get("/api/v1/intel/test-123")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["intel_id"] == "test-123"
    assert "_id" not in data["data"]
    assert data["meta"]["trace_id"] == "trace-456"


def test_intel_detail_not_found(api_client):
    mock_mongo.intel.find_one.return_value = None
    response = api_client.get("/api/v1/intel/test-123")
    assert response.status_code == 404


def test_intel_lookup_survives_uuid_codec_errors(api_client):
    intel_id = "563395b3-6569-3348-3b36-1be4ff683c69"

    async def reject_uuid(query, *_args, **_kwargs):
        value = query.get("intel_id")
        if type(value).__name__ == "UUID":
            raise ValueError(
                "cannot encode native uuid.UUID with UuidRepresentation.UNSPECIFIED"
            )
        if isinstance(value, dict) and "$regex" in value:
            raise RuntimeError("$regex only works on strings")

    mock_mongo.intel.find_one.side_effect = reject_uuid
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = []
    mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = mock_cursor
    mock_mongo.intel.count_documents.return_value = 0

    detail = api_client.get(f"/api/v1/intel/{intel_id}")
    assert detail.status_code == 404
    listed = api_client.get(f"/api/v1/intel?intel_id={intel_id}&limit=25")
    assert listed.status_code == 200
    assert listed.json()["data"] == []
    evidence = api_client.get(f"/api/v1/intel/{intel_id}/evidence")
    assert evidence.status_code == 404
    mock_mongo.intel.find_one.side_effect = None


def test_intel_list_skips_partial_documents(api_client):
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "intel_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "ingest_id": "test-ingest",
            "captured_at": "2024-01-01T12:00:00Z",
            "intent": None,
            "severity": None,
            "products": None,
            "geo": None,
            "entities": {"vendors": None},
            "tags": None,
        }
    ]
    mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = mock_cursor
    mock_mongo.intel.count_documents.return_value = 1

    response = api_client.get("/api/v1/intel")
    assert response.status_code == 200
    assert response.json()["data"][0]["intel_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_intel_detail_resolves_graph_prefix(api_client):
    intel_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mock_mongo.intel.find_one.side_effect = [
        None,
        {
            "_id": "internal-mongo-id",
            "intel_id": intel_id,
            "trace_id": "trace-456",
        },
    ]
    response = api_client.get(f"/api/v1/intel/intel:{intel_id}")
    assert response.status_code == 200
    assert response.json()["data"]["intel_id"] == intel_id
    mock_mongo.intel.find_one.side_effect = None


def test_graph_endpoint(api_client):
    mock_neo4j.get_subgraph.return_value = {
        "nodes": [{"id": "1", "label": "VendorX", "type": "Vendor", "properties": {}}],
        "edges": [],
        "truncated": False,
        "limits": {"max_nodes": 200, "max_edges": 0},
    }

    response = api_client.get("/api/v1/graph?center=VendorX&depth=2")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["label"] == "VendorX"

    mock_neo4j.get_subgraph.assert_called_once_with(
        center="VendorX", depth=2, node_type="Vendor", max_nodes=200
    )


def test_search_endpoint(api_client):
    mock_mongo.search_intel = AsyncMock(
        return_value={"total": 1, "records": [{"intel_id": "test-123"}]}
    )

    response = api_client.get("/api/v1/search?q=mdma")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["pagination"]["total"] == 1

    mock_mongo.search_intel.assert_called_once_with(query="mdma", limit=50, lang=None)


def test_intel_list_by_intel_id(api_client):
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "intel_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "ingest_id": "test-ingest",
            "captured_at": "2024-01-01T12:00:00Z",
            "intent": {"label": "sale", "score": 0.95},
            "severity": {"band": "high", "score": 85.0},
        }
    ]
    mock_mongo.intel.find.return_value.sort.return_value.limit.return_value = mock_cursor
    mock_mongo.intel.count_documents.return_value = 1

    response = api_client.get(
        "/api/v1/intel?intel_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["intel_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    query = mock_mongo.intel.find.call_args.args[0]
    assert query["intel_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_geo_dashboard_does_not_require_products(api_client):
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "_id": "adajan",
            "neighborhood": "adajan",
            "count": 2,
            "avg_severity": 40.0,
            "product_lists": [[], [{"canonical": "cannabis"}]],
        }
    ]
    mock_mongo.intel.aggregate = MagicMock(return_value=mock_cursor)

    response = api_client.get("/api/v1/dashboards/geo")
    assert response.status_code == 200
    payload = response.json()["data"][0]
    assert payload["neighborhood"] == "adajan"
    assert payload["count"] == 2
    assert payload["top_products"] == ["cannabis"]
