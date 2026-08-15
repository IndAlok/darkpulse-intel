from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep, SettingsDep
from darkpulse.api.security import AnalystDep, ViewerDep
from darkpulse.evidence.sealing import EvidenceSealer
from darkpulse.models import ApiEnvelope

router = APIRouter(prefix="/evidence", tags=["Evidence"])


class EvidenceSealRequest(BaseModel):
    payload: str = Field(min_length=1, max_length=100_000)


class EvidenceVerifyRequest(BaseModel):
    payload: str = Field(min_length=1, max_length=100_000)
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
    last = await db.evidence.find_one(sort=[("sealed_at", -1)])
    previous_hash = last.get("hash_sha256") if last else None

    sealer = EvidenceSealer(
        tsa_url=settings.evidence.rfc3161_tsa_url,
        rfc3161_enabled=settings.evidence.rfc3161_enabled,
    )
    seal = await sealer.seal(payload, db, previous_hash=previous_hash)
    return seal.model_dump()


@router.post("/seal", response_model=ApiEnvelope)
async def seal_evidence(
    req: EvidenceSealRequest,
    request: Request,
    db: MongoDep,
    settings: SettingsDep,
    principal: AnalystDep,
) -> dict[str, Any]:
    doc = await generate_seal(req.payload.encode("utf-8"), db, settings)
    await audit_event(
        db,
        request,
        principal,
        "evidence.seal",
        target_type="evidence",
        target_id=doc["hash_sha256"],
    )
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
    cursor = db.evidence.find().sort("sealed_at", 1)
    docs = await cursor.to_list(length=10000)

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
            "verified": len(breaks) == 0,
            "record_count": len(docs),
            "breaks": breaks,
        },
        "meta": {},
    }


@router.get("/{hash_sha256}", response_model=ApiEnvelope)
async def get_evidence_seal(
    hash_sha256: str, request: Request, db: MongoDep, principal: ViewerDep
) -> dict[str, Any]:
    doc = await db.evidence.find_one({"hash_sha256": hash_sha256}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Evidence seal not found")
    await audit_event(
        db, request, principal, "evidence.read", target_type="evidence", target_id=hash_sha256
    )
    return {"data": EvidenceSealResponse(**doc), "meta": {}}
