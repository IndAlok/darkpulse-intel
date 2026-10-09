from __future__ import annotations

import hashlib
import time
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class EvidenceSeal(BaseModel):
    hash_sha256: str
    tsa_token: str = ""
    tsa_verified: bool = False
    sealed_at: int
    provenance: str = "DarkPulse/hash-only"
    previous_hash: str | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EvidenceSealer:
    async def seal(
        self,
        payload: bytes,
        mongo: Any,
        *,
        previous_hash: str | None = None,
    ) -> EvidenceSeal:
        seal = EvidenceSeal(
            hash_sha256=sha256_hex(payload),
            sealed_at=int(time.time()),
            previous_hash=previous_hash,
        )
        await mongo.evidence.insert_one(seal.model_dump())
        logger.info("evidence.sealed", hash_sha256=seal.hash_sha256)
        return seal

    def verify(self, payload: bytes, seal: EvidenceSeal) -> bool:
        return sha256_hex(payload) == seal.hash_sha256
