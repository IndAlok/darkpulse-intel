from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import OperationFailure

from darkpulse.storage.mongodb import MongoManager


def make_manager() -> MagicMock:
    manager = MagicMock()
    manager.search_intel = MongoManager.search_intel.__get__(manager, MongoManager)
    manager._search_intel_fallback = MongoManager._search_intel_fallback.__get__(
        manager, MongoManager
    )
    manager.intel = MagicMock()
    manager.intel.count_documents = AsyncMock(return_value=3)
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[{"intel_id": "intel-1", "severity": {"score": 90}}])
    manager.intel.aggregate = MagicMock(return_value=cursor)
    return manager


@pytest.mark.asyncio
async def test_search_intel_builds_text_query() -> None:
    manager = make_manager()
    result = await manager.search_intel("mdma", limit=50)
    assert result == {"total": 3, "records": [{"intel_id": "intel-1", "severity": {"score": 90}}]}
    pipeline = manager.intel.aggregate.call_args.args[0]
    match = pipeline[0]["$match"]
    assert "$text" in match
    assert "mdma" in match["$text"]["$search"]
    assert "$unset" in pipeline[-1]
    manager.intel.count_documents.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_intel_hinglish_matches_code_mixed() -> None:
    manager = make_manager()
    await manager.search_intel("maal", limit=10, lang="hinglish")
    pipeline = manager.intel.aggregate.call_args.args[0]
    match = pipeline[0]["$match"]
    language = match["$and"][1] if "$and" in match else match
    assert language["$or"] == [
        {"language.detected": "hinglish"},
        {"language.code_mixed": True},
        {"language.romanized": True},
    ]


@pytest.mark.asyncio
async def test_search_intel_applies_lang_and_caps_limit() -> None:
    manager = make_manager()
    await manager.search_intel("mdma", limit=5000, lang="hi")
    pipeline = manager.intel.aggregate.call_args.args[0]
    match = pipeline[0]["$match"]
    language = match["$and"][1] if "$and" in match else match
    assert language["language.detected"] == "hi"
    limit_stage = next(stage for stage in pipeline if "$limit" in stage)
    assert limit_stage["$limit"] == 200


@pytest.mark.asyncio
async def test_search_intel_scores_and_sorts() -> None:
    manager = make_manager()
    await manager.search_intel("cocaine", limit=10)
    pipeline = manager.intel.aggregate.call_args.args[0]
    sort_stage = next(stage for stage in pipeline if "$sort" in stage)
    assert sort_stage["$sort"]["severity.score"] == -1
    assert sort_stage["$sort"]["text_score"] == -1
    score_stage = next(stage for stage in pipeline if "$addFields" in stage)
    assert score_stage["$addFields"]["text_score"] == {"$meta": "textScore"}


@pytest.mark.asyncio
async def test_search_intel_falls_back_without_text_index() -> None:
    manager = make_manager()
    manager.intel.aggregate.return_value.to_list = AsyncMock(
        side_effect=OperationFailure("text index required", 27)
    )
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[{"intel_id": "intel-2"}])
    manager.intel.find.return_value = cursor
    manager.intel.count_documents = AsyncMock(return_value=1)
    result = await manager.search_intel("surat", limit=10, lang="hinglish")
    assert result["total"] == 1
    assert result["records"][0]["intel_id"] == "intel-2"
    manager.intel.find.assert_called_once()


@pytest.mark.asyncio
async def test_search_intel_falls_back_when_text_query_is_empty() -> None:
    manager = make_manager()
    manager.intel.aggregate.return_value.to_list = AsyncMock(return_value=[])
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(
        return_value=[{"intel_id": "intel-weed", "products": [{"canonical": "cannabis"}]}]
    )
    manager.intel.find.return_value = cursor
    manager.intel.count_documents = AsyncMock(return_value=1)
    result = await manager.search_intel("weed", limit=10)
    assert result["total"] == 1
    assert result["records"][0]["intel_id"] == "intel-weed"
    query = manager.intel.find.call_args.args[0]
    encoded = str(query)
    assert "weed" in encoded
    assert "cannabis" in encoded


@pytest.mark.asyncio
async def test_search_intel_resolves_exact_intel_id() -> None:
    manager = make_manager()
    intel_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    manager.intel.find_one = AsyncMock(return_value={"intel_id": intel_id})
    result = await manager.search_intel(f"intel:{intel_id}")
    assert result == {"total": 1, "records": [{"intel_id": intel_id}]}
    manager.intel.find_one.assert_awaited_once()
