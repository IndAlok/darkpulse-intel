# ruff: noqa: S101
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_mongo.alerts_history.find = MagicMock()
app.dependency_overrides[get_mongo] = lambda: mock_mongo


@pytest.fixture
def alerts_client():
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    with TestClient(app) as c:
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
