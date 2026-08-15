import sys

sys.path.insert(0, "src")

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_neo4j, get_settings
from darkpulse.config import Settings

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()
patch("darkpulse.broker.processor.MongoProcessor.stop", new_callable=AsyncMock).start()
patch("darkpulse.storage.mongodb.MongoManager.connect", new_callable=AsyncMock).start()
patch(
    "darkpulse.storage.mongodb.MongoManager.ensure_application_defaults", new_callable=AsyncMock
).start()
patch("darkpulse.storage.mongodb.MongoManager.close", new_callable=AsyncMock).start()
patch("darkpulse.storage.mongodb.MongoManager.health", new_callable=AsyncMock).start()
patch("darkpulse.storage.neo4j.Neo4jManager.connect", new_callable=AsyncMock).start()
patch("darkpulse.storage.neo4j.Neo4jManager.close", new_callable=AsyncMock).start()
patch("darkpulse.storage.neo4j.Neo4jManager.health", new_callable=AsyncMock).start()


def make_cursor(items):
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=items)
    return cursor


mock_mongo = AsyncMock()
mock_mongo.intel.find = MagicMock(return_value=make_cursor([]))
mock_mongo.raw_ingest.find = MagicMock(return_value=make_cursor([]))
mock_mongo.intel.count_documents = AsyncMock(return_value=0)
mock_mongo.search_intel = AsyncMock(return_value={"total": 0, "records": []})
mock_mongo.intel.aggregate = MagicMock(return_value=make_cursor([]))
mock_mongo.alerts_history.find = MagicMock(return_value=make_cursor([]))
mock_mongo.alerts_config.find_one = AsyncMock(return_value=None)
mock_mongo.watchlists.find = MagicMock(return_value=make_cursor([]))
mock_mongo.slang.find = MagicMock(return_value=make_cursor([]))
mock_mongo.evidence.find_one = AsyncMock(return_value=None)
mock_mongo.evidence.find = MagicMock(return_value=make_cursor([]))
mock_mongo.evidence.insert_one = AsyncMock()
mock_neo4j = AsyncMock()
mock_neo4j.get_subgraph = AsyncMock(
    return_value={
        "nodes": [],
        "edges": [],
        "truncated": False,
        "limits": {"max_nodes": 200, "max_edges": 0},
    }
)

app.dependency_overrides[get_mongo] = lambda: mock_mongo
app.dependency_overrides[get_neo4j] = lambda: mock_neo4j
app.dependency_overrides[get_settings] = lambda: Settings()

with TestClient(app) as c:
    paths = [
        "/api/v1/intel",
        "/api/v1/actors",
        "/api/v1/graph",
        "/api/v1/graph?node_type=Wallet",
        "/api/v1/search?q=mdma",
        "/api/v1/dashboards/trends",
        "/api/v1/dashboards/sources",
        "/api/v1/dashboards/geo",
        "/api/v1/watchlists",
        "/api/v1/slang",
        "/api/v1/slang/candidates",
        "/api/v1/alerts/config",
        "/api/v1/alerts/history",
        "/api/v1/export?format=csv",
        "/api/v1/export?format=json",
        "/api/v1/evidence/seal",
        "/api/v1/evidence/verify",
    ]
    ok = True
    for path in paths:
        method = "post" if path.endswith("/evidence/seal") else "get"
        kwargs = {"json": {"payload": "test"}} if method == "post" else {}
        r = getattr(c, method)(path, **kwargs)
        status = r.status_code
        if status >= 400:
            ok = False
        print(f"{path} -> {status}")
    print("ALL ROUTES OK" if ok else "SOME ROUTES FAILED")
