from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from darkpulse.models import RawIngest
from darkpulse.storage.mongodb import MongoManager


class RecordPublisher(Protocol):
    async def start(self) -> None: ...

    async def publish(self, record: RawIngest) -> None: ...

    async def stop(self) -> None: ...


class InMemoryPublisher:
    def __init__(self) -> None:
        self.records: list[RawIngest] = []

    async def start(self) -> None:
        return None

    async def publish(self, record: RawIngest) -> None:
        self.records.append(record)

    async def stop(self) -> None:
        return None


class MongoPublisher:
    def __init__(self, mongo: MongoManager) -> None:
        self._mongo = mongo

    async def start(self) -> None:
        return None

    async def publish(self, record: RawIngest) -> None:
        now = datetime.now(UTC)
        raw_doc = record.model_dump(mode="python")
        raw_doc["ingest_id"] = str(record.ingest_id)
        raw_doc["trace_id"] = str(record.trace_id)
        await self._mongo.raw_ingest.update_one(
            {"ingest_id": str(record.ingest_id)},
            {
                "$setOnInsert": {
                    **raw_doc,
                    "processing": {"status": "pending", "attempts": 0, "updated_at": now},
                }
            },
            upsert=True,
        )

    async def stop(self) -> None:
        return None
