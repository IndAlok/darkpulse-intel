from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep, SettingsDep
from darkpulse.api.routes.alerts import _validate_id
from darkpulse.api.security import AnalystDep, ViewerDep
from darkpulse.evidence.sealing import EvidenceSealer, sha256_hex
from darkpulse.models import ApiEnvelope

router = APIRouter(prefix="/evidence", tags=["Evidence"])
_VERIFY_CAP = 100_000


class EvidenceSealRequest(BaseModel):
    payload: str = Field(min_length=1, max_length=100_000)


class EvidenceVerifyRequest(BaseModel):
    payload: str = Field(min_length=1, max_length=5_000_000)
    hash_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceSealResponse(BaseModel):
    hash_sha256: str
    tsa_token: str
    tsa_verified: bool
    sealed_at: int
    provenance: str
    previous_hash: str | None = None


async def generate_seal(
    payload: bytes,
    db: MongoDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    sealer = EvidenceSealer()
    payload_hash = sha256_hex(payload)
    for _ in range(5):
        existing = await db.evidence.find_one({"hash_sha256": payload_hash})
        if existing:
            return {key: value for key, value in existing.items() if key != "_id"}
        last = await db.evidence.find_one(sort=[("_id", -1)])
        previous_hash = last.get("hash_sha256") if last else None
        try:
            seal = await sealer.seal(payload, db, previous_hash=previous_hash)
        except DuplicateKeyError:
            continue
        return seal.model_dump()
    raise HTTPException(status_code=409, detail="Evidence chain conflict")


@router.post("/seal", response_model=ApiEnvelope)
async def seal_evidence(
    req: EvidenceSealRequest,
    request: Request,
    db: MongoDep,
    settings: SettingsDep,
    principal: AnalystDep,
) -> dict[str, Any]:
    payload = req.payload.encode("utf-8")
    await audit_event(
        db,
        request,
        principal,
        "evidence.seal",
        target_type="evidence",
        target_id=sha256_hex(payload),
    )
    doc = await generate_seal(payload, db, settings)
    return {"data": EvidenceSealResponse(**doc), "meta": {}}


@router.post("/verify")
async def verify_payload(
    req: EvidenceVerifyRequest,
    request: Request,
    db: MongoDep,
    principal: ViewerDep,
) -> dict[str, Any]:
    import hashlib

    payload_hash = hashlib.sha256(req.payload.encode("utf-8")).hexdigest()
    ledger = await db.evidence.find_one({"hash_sha256": req.hash_sha256}, {"_id": 0})
    matches = payload_hash == req.hash_sha256
    await audit_event(
        db,
        request,
        principal,
        "evidence.verify_payload",
        target_type="evidence",
        target_id=req.hash_sha256,
        metadata={"matches": matches},
    )
    return {
        "data": {
            "matches": matches,
            "payload_hash": payload_hash,
            "ledger_recorded": bool(ledger),
        },
        "meta": {},
    }


@router.get("/verify")
async def verify_chain(request: Request, db: MongoDep, principal: ViewerDep) -> dict[str, Any]:
    docs = await db.evidence.find().sort("_id", 1).to_list(length=_VERIFY_CAP + 1)
    truncated = len(docs) > _VERIFY_CAP
    docs = docs[:_VERIFY_CAP]

    breaks = []
    previous = None
    for doc in docs:
        if previous is not None and doc.get("previous_hash") != previous:
            breaks.append(
                {
                    "record_id": str(doc.get("_id", "")),
                    "expected_previous": previous,
                    "actual_previous": doc.get("previous_hash"),
                }
            )
        previous = doc.get("hash_sha256")

    await audit_event(
        db,
        request,
        principal,
        "evidence.verify",
        target_type="evidence",
        metadata={"record_count": len(docs), "breaks": len(breaks)},
    )
    return {
        "data": {
            "verified": not breaks and not truncated,
            "record_count": len(docs),
            "truncated": truncated,
            "breaks": breaks,
        },
        "meta": {},
    }


@router.get("/{hash_sha256}", response_model=ApiEnvelope)
async def get_evidence_seal(
    hash_sha256: str, request: Request, db: MongoDep, principal: ViewerDep
) -> dict[str, Any]:
    _validate_id(hash_sha256, "hash_sha256")
    doc = await db.evidence.find_one({"hash_sha256": hash_sha256}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Evidence seal not found")
    await audit_event(
        db, request, principal, "evidence.read", target_type="evidence", target_id=hash_sha256
    )
    return {"data": EvidenceSealResponse(**doc), "meta": {}}
