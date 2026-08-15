from unittest.mock import AsyncMock, MagicMock

import pytest

from darkpulse.ingestion.publisher import InMemoryPublisher, MongoPublisher
from darkpulse.storage.mongodb import MongoManager


@pytest.mark.asyncio
async def test_mongo_publisher_writes_pending_raw_doc() -> None:
    mongo = MagicMock(spec=MongoManager)
    mongo.raw_ingest = MagicMock()
    mongo.raw_ingest.update_one = AsyncMock()
    publisher = MongoPublisher(mongo)
    record = MagicMock()
    record.ingest_id = "ingest-1"
    record.trace_id = "trace-1"
    record.model_dump.return_value = {"ingest_id": "ingest-1", "trace_id": "trace-1"}

    await publisher.publish(record)

    mongo.raw_ingest.update_one.assert_awaited_once()
    call = mongo.raw_ingest.update_one.await_args
    assert call.args[0] == {"ingest_id": "ingest-1"}
    assert call.kwargs["upsert"] is True
    inserted = call.args[1]["$setOnInsert"]
    assert inserted["processing"]["status"] == "pending"
    assert inserted["processing"]["attempts"] == 0
    assert inserted["ingest_id"] == "ingest-1"
    assert inserted["trace_id"] == "trace-1"


@pytest.mark.asyncio
async def test_mongo_publisher_lifecycle_is_noop() -> None:
    mongo = MagicMock(spec=MongoManager)
    publisher = MongoPublisher(mongo)
    await publisher.start()
    await publisher.stop()


@pytest.mark.asyncio
async def test_in_memory_publisher_records_published() -> None:
    publisher = InMemoryPublisher()
    record = MagicMock()
    await publisher.publish(record)
    assert publisher.records == [record]
