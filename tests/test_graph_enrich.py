import pytest

from darkpulse.api.graph_enrich import enrich_graph_nodes, hydrate_graph


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, *_args: object, **_kwargs: object) -> "_Cursor":
        return self

    def limit(self, *_args: object, **_kwargs: object) -> "_Cursor":
        return self

    async def to_list(self, length: int) -> list[dict]:
        return self._docs[:length]


class _Mongo:
    def __init__(self, docs: list[dict]) -> None:
        self.intel = self
        self._docs = docs

    def find(self, query: dict, *_args: object, **_kwargs: object) -> _Cursor:
        wanted = query.get("intel_id")
        if isinstance(wanted, dict) and "$in" in wanted:
            allowed = {str(item) for item in wanted["$in"]}
            return _Cursor([doc for doc in self._docs if str(doc["intel_id"]) in allowed])
        return _Cursor(self._docs)

    async def find_one(self, query: dict, *_args: object, **_kwargs: object) -> dict | None:
        intel_id = query.get("intel_id")
        if not isinstance(intel_id, str):
            return None
        for doc in self._docs:
            if str(doc["intel_id"]) == intel_id:
                return doc
        return None


def _doc(intel_id: str) -> dict:
    return {
        "intel_id": intel_id,
        "products": [{"canonical": "cannabis"}],
        "geo": {"neighborhood": "adajan"},
        "intent": {"label": "sale"},
        "severity": {"band": "high"},
        "captured_at": "2026-08-16T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_enrich_graph_nodes_resolves_live_intel_labels() -> None:
    intel_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    nodes = await enrich_graph_nodes(
        _Mongo([_doc(intel_id)]),
        [
            {
                "id": f"intel:{intel_id}",
                "label": intel_id,
                "type": "IntelRef",
                "properties": {"intel_id": intel_id},
            },
            {"id": "vendor:alice", "label": "alice", "type": "Vendor", "properties": {}},
        ],
    )
    assert nodes[0]["label"] == "cannabis · adajan"
    assert nodes[0]["properties"]["available"] is True
    assert nodes[1]["label"] == "alice"


@pytest.mark.asyncio
async def test_enrich_graph_nodes_marks_missing_intel() -> None:
    nodes = await enrich_graph_nodes(
        _Mongo([]),
        [
            {
                "id": "intel:missing",
                "label": "missing",
                "type": "IntelRef",
                "properties": {"intel_id": "missing"},
            }
        ],
    )
    assert nodes[0]["properties"]["available"] is False


@pytest.mark.asyncio
async def test_hydrate_replaces_orphan_intel_with_live_corpus() -> None:
    live_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    nodes, _edges = await hydrate_graph(
        _Mongo([_doc(live_id)]),
        [
            {
                "id": "intel:missing",
                "label": "missing",
                "type": "IntelRef",
                "properties": {"intel_id": "missing"},
            },
            {"id": "vendor:alice", "label": "alice", "type": "Vendor", "properties": {}},
        ],
        [],
    )
    intel_nodes = [node for node in nodes if node["type"] == "IntelRef"]
    assert intel_nodes
    assert all(node["properties"]["available"] is True for node in intel_nodes)
    assert intel_nodes[0]["properties"]["intel_id"] == live_id
    assert any(node["id"] == "vendor:alice" for node in nodes)
