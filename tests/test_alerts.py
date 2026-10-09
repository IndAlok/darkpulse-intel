# ruff: noqa: S101
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings

mock_mongo = AsyncMock()
mock_mongo.alerts_history.find = MagicMock()
app.dependency_overrides[get_mongo] = lambda: mock_mongo

@pytest.fixture
def alerts_client(auth_settings, auth_headers):
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as c:
        c.headers.update(auth_headers)
        yield c
    app.dependency_overrides.clear()

def test_get_alert_config(alerts_client: TestClient) -> None:
    mock_mongo.alerts_config.find_one.return_value = {
        "_id": "default",
        "rules": [{"name": "High Severity", "severity_min": 80}],
    }

    response = alerts_client.get("/api/v1/alerts/config")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]["rules"]) == 1
    assert data["data"]["rules"][0]["name"] == "High Severity"

def test_update_alert_config(alerts_client: TestClient) -> None:
    mock_mongo.alerts_config.update_one = AsyncMock()

    payload = {"rules": [{"name": "Critical", "severity_min": 95}]}

    response = alerts_client.put("/api/v1/alerts/config", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["rules"][0]["name"] == "Critical"

def test_history_cursor_matches_object_id_and_timestamp() -> None:
    from bson import ObjectId

    from darkpulse.api.routes.alerts import history_page_query

    raw = "656f1f77bcf86cd799439011"
    query = history_page_query(f"2024-01-02T00:00:00+00:00|{raw}")
    encoded = str(query)
    assert raw in encoded
    assert str(ObjectId(raw)) in encoded
    assert "triggered_at" in query["$or"][0]

@pytest.mark.asyncio
async def test_broadcast_publishes_to_the_shared_channel() -> None:
    from darkpulse.api.routes import alerts as alerts_route

    published: dict[str, str] = {}

    class Publisher:
        async def publish(self, channel: str, data: str) -> None:
            published["channel"] = channel
            published["data"] = data

    alerts_route._relay_client = Publisher()
    try:
        await alerts_route.broadcast_alert({"id": "a-1", "wallet": "bc1secret"})
    finally:
        alerts_route._relay_client = None
    assert published["channel"] == "dp:alerts"
    assert "bc1secret" in published["data"]

def test_get_alert_history(alerts_client: TestClient) -> None:
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "_id": "hist-1",
            "rule_name": "High Severity",
            "intel_id": "intel-123",
            "triggered_at": "2024-01-01T00:00:00Z",
            "severity_score": 85.0,
        }
    ]
    mock_mongo.alerts_history.find.return_value.sort.return_value = mock_cursor

    response = alerts_client.get("/api/v1/alerts/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["id"] == "hist-1"
