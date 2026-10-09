# ruff: noqa: S101
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings

mock_mongo = AsyncMock()
mock_mongo.watchlists.find = MagicMock()
app.dependency_overrides[get_mongo] = lambda: mock_mongo

@pytest.fixture
def wl_client(auth_settings, auth_headers):
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as c:
        c.headers.update(auth_headers)
        yield c
    app.dependency_overrides.clear()

def test_get_watchlists(wl_client: TestClient) -> None:
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(
        return_value=[
            {
                "_id": "wl-1",
                "name": "Opioids",
                "type": "keyword",
                "terms": ["fentanyl", "oxy"],
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]
    )
    mock_mongo.watchlists.find.return_value = mock_cursor

    response = wl_client.get("/api/v1/watchlists")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["id"] == "wl-1"
    assert data["data"][0]["name"] == "Opioids"

def test_create_watchlist(wl_client: TestClient) -> None:
    mock_mongo.watchlists.insert_one = AsyncMock()

    payload = {"name": "Weapons", "terms": ["glock", "ak47"]}

    response = wl_client.post("/api/v1/watchlists", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["name"] == "Weapons"
    assert data["data"]["terms"] == ["glock", "ak47"]
    assert "id" in data["data"]
