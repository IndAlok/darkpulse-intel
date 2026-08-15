# ruff: noqa: S101
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()

mock_mongo = AsyncMock()
mock_mongo.slang.find = MagicMock()
app.dependency_overrides[get_mongo] = lambda: mock_mongo


@pytest.fixture
def slang_client():
    app.dependency_overrides[get_mongo] = lambda: mock_mongo
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_slang(slang_client: TestClient) -> None:
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(
        return_value=[
            {
                "_id": "sl-1",
                "term": "snow",
                "meaning": "cocaine",
                "lang": "en",
                "newly_discovered": False,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]
    )
    mock_mongo.slang.find.return_value = mock_cursor

    response = slang_client.get("/api/v1/slang")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["id"] == "sl-1"
    assert data["data"][0]["term"] == "snow"


def test_create_slang(slang_client: TestClient) -> None:
    mock_mongo.slang.insert_one = AsyncMock()

    payload = {"term": "ice", "meaning": "meth", "lang": "en", "newly_discovered": True}

    response = slang_client.post("/api/v1/slang", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["term"] == "ice"
    assert data["data"]["meaning"] == "meth"
    assert "id" in data["data"]
