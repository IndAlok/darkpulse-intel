from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from darkpulse.models import RawIngest
from darkpulse.storage.mongodb import MongoManager


class RecordPublisher(Protocol):
    async def start(self) -> None: ...

    async def publish(self, record: RawIngest) -> bool: ...

    async def stop(self) -> None: ...


class InMemoryPublisher:
    def __init__(self) -> None:
        self.records: list[RawIngest] = []

    async def start(self) -> None:
        return None

    async def publish(self, record: RawIngest) -> bool:
        self.records.append(record)
        return True

    async def stop(self) -> None:
        return None


class MongoPublisher:
    def __init__(self, mongo: MongoManager) -> None:
        self._mongo = mongo

    async def start(self) -> None:
        return None

    async def publish(self, record: RawIngest) -> bool:
        now = datetime.now(UTC)
        raw_doc = record.model_dump(mode="python")
        raw_doc["ingest_id"] = str(record.ingest_id)
        raw_doc["trace_id"] = str(record.trace_id)
        result = await self._mongo.raw_ingest.update_one(
            {"dedup_key": record.dedup_key},
            {
                "$setOnInsert": {
                    **raw_doc,
                    "processing": {"status": "pending", "attempts": 0, "updated_at": now},
                }
            },
            upsert=True,
        )
        return result.upserted_id is not None

    async def stop(self) -> None:
        return None
