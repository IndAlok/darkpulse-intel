from __future__ import annotations

import hashlib
import time
from typing import Any

import structlog
from pyasn1.codec.der import decoder, encoder
from pyasn1.type import univ
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class EvidenceSeal(BaseModel):
    hash_sha256: str
    tsa_token: str
    tsa_verified: bool
    sealed_at: int
    provenance: str
    previous_hash: str | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_tsa_request(payload_hash: str) -> bytes:
    hash_alg = univ.Sequence()
    hash_alg.setComponentByPosition(0, univ.ObjectIdentifier("2.16.840.1.101.3.4.2.1"))
    hash_alg.setComponentByPosition(1, univ.Null(""))

    hashed_message = univ.OctetString(hexValue=payload_hash)

    message_imprint_seq = univ.Sequence()
    message_imprint_seq.setComponentByPosition(0, hash_alg)
    message_imprint_seq.setComponentByPosition(1, hashed_message)

    nonce = univ.Integer(int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF)

    request = univ.Sequence()
    request.setComponentByPosition(0, univ.Integer(1))
    request.setComponentByPosition(1, message_imprint_seq)
    request.setComponentByPosition(2, univ.Boolean(False))
    request.setComponentByPosition(3, nonce)
    request.setComponentByPosition(4, univ.Boolean(True))

    encoded: bytes = encoder.encode(request)
    return encoded


def parse_tsa_response(response_bytes: bytes) -> tuple[int, bytes]:
    try:
        decoded, _ = decoder.decode(response_bytes, asn1Spec=univ.Sequence())
        status = int(decoded.getComponentByPosition(0))
        token = b""
        if len(decoded) > 1:
            token = encoder.encode(decoded.getComponentByPosition(1))
        return status, token
    except Exception as exc:
        logger.warning("evidence.tsa_response_parse_failed", error=str(exc))
        return -1, b""


def request_tsa(tsa_url: str, payload_hash: str, timeout: int = 10) -> str | None:
    import requests

    try:
        request_der = build_tsa_request(payload_hash)
        response = requests.post(
            tsa_url,
            data=request_der,
            headers={
                "Content-Type": "application/timestamp-query",
                "Accept": "application/timestamp-reply",
            },
            timeout=timeout,
        )
        if response.status_code != 200:
            logger.warning("evidence.tsa_http_error", status=response.status_code)
            return None
        status, token = parse_tsa_response(response.content)
        if status != 0 or not token:
            logger.warning("evidence.tsa_rejected", status=status)
            return None
        return sha256_hex(token)
    except Exception as exc:
        logger.warning("evidence.tsa_request_failed", error=str(exc))
        return None


class EvidenceSealer:
    def __init__(self, tsa_url: str = "", rfc3161_enabled: bool = False) -> None:
        self._tsa_url = tsa_url
        self._rfc3161_enabled = rfc3161_enabled

    async def seal(
        self,
        payload: bytes,
        mongo: Any,
        *,
        previous_hash: str | None = None,
    ) -> EvidenceSeal:
        payload_hash = sha256_hex(payload)
        sealed_at = int(time.time())

        tsa_token = ""
        tsa_verified = False
        if self._rfc3161_enabled and self._tsa_url:
            import asyncio

            tsa_token = await asyncio.to_thread(
                lambda: request_tsa(self._tsa_url, payload_hash) or ""
            )
            tsa_verified = bool(tsa_token)

        provenance = "DarkPulse/RFC3161" if tsa_verified else "DarkPulse/hash-only"

        seal = EvidenceSeal(
            hash_sha256=payload_hash,
            tsa_token=tsa_token,
            tsa_verified=tsa_verified,
            sealed_at=sealed_at,
            provenance=provenance,
            previous_hash=previous_hash,
        )
        await mongo.evidence.insert_one(seal.model_dump())
        logger.info("evidence.sealed", hash_sha256=payload_hash, tsa_verified=tsa_verified)
        return seal

    def verify(self, payload: bytes, seal: EvidenceSeal) -> bool:
        return sha256_hex(payload) == seal.hash_sha256
