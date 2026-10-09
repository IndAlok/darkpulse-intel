import asyncio
import csv
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep, SettingsDep
from darkpulse.api.routes.evidence import generate_seal
from darkpulse.api.security import AnalystDep, ViewerDep
from darkpulse.evidence.sealing import sha256_hex

router = APIRouter(prefix="/export", tags=["Export"])
MAX_EXPORT_ROWS = 1000


def _flatten_doc(doc: dict[str, Any], source_ref: str = "") -> dict[str, Any]:
    severity = doc.get("severity") or {}
    intent = doc.get("intent") or {}
    geo = doc.get("geo") or {}
    entities = doc.get("entities") or {}
    products = doc.get("products", [])
    slang = doc.get("slang_decoded", [])
    return {
        "intel_id": doc.get("intel_id", ""),
        "ingest_id": doc.get("ingest_id", ""),
        "trace_id": doc.get("trace_id", ""),
        "captured_at": doc.get("captured_at", ""),
        "severity_score": severity.get("score", ""),
        "severity_band": severity.get("band", ""),
        "intent_label": intent.get("label", ""),
        "intent_score": intent.get("score", ""),
        "products": "; ".join(p.get("canonical", "") for p in products if p.get("canonical")),
        "slang_decoded": "; ".join(s.get("term", "") for s in slang if s.get("term")),
        "vendor_aliases": "; ".join(
            v.get("alias", "") for v in entities.get("vendors", []) if v.get("alias")
        ),
        "crypto_wallets": "; ".join(
            w.get("address", "") for w in entities.get("crypto_wallets", []) if w.get("address")
        ),
        "contacts": "; ".join(
            c.get("value_redacted", "")
            for c in entities.get("contacts", [])
            if c.get("value_redacted")
        ),
        "neighborhood": geo.get("neighborhood", ""),
        "source_class": doc.get("source_class", ""),
        "confidence": doc.get("confidence", ""),
        "content_hash": doc.get("content_hash", ""),
        "source_ref": source_ref,
    }


def _csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _pdf_text(value: str) -> str:
    encoded = value.encode("cp1252", errors="replace").decode("cp1252")
    return encoded if encoded == value else f"{encoded} [non-Latin script omitted]"


def _pdf_report(records: list[dict[str, Any]]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen.canvas import Canvas

    output = io.BytesIO()
    canvas = Canvas(output, pagesize=A4)
    width, height = A4
    y = height - 20 * mm
    canvas.setTitle("DarkPulse Intelligence Report")
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(18 * mm, y, "DarkPulse Intelligence Report")
    y -= 7 * mm
    canvas.setFont("Helvetica", 8)
    canvas.drawString(
        18 * mm,
        y,
        f"{len(records)} governed records. Not a claim of legal admissibility.",
    )
    y -= 10 * mm
    for record in records:
        if y < 32 * mm:
            canvas.showPage()
            canvas.setFont("Helvetica", 8)
            y = height - 20 * mm
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(
            18 * mm,
            y,
            _pdf_text(
                f"{str(record.get('severity_band') or 'info').upper()}  "
                f"{record.get('intent_label') or 'unknown'}  "
                f"{record.get('neighborhood') or 'Location pending'}"
            ),
        )
        y -= 5 * mm
        canvas.setFont("Helvetica", 8)
        for line in (
            f"Intel ID: {record.get('intel_id') or 'unknown'}",
            f"Captured: {record.get('captured_at') or 'unknown'}",
            f"Products: {record.get('products') or 'Unspecified'}",
            f"Vendors: {record.get('vendor_aliases') or 'None identified'}",
            f"Wallets: {record.get('crypto_wallets') or 'None identified'}",
            f"Source: {record.get('source_class') or 'unknown'}  "
            f"Confidence: {record.get('confidence') or '-'}",
        ):
            line = _pdf_text(line)
            if stringWidth(line, "Helvetica", 8) > width - 36 * mm:
                line = line[:110] + "..."
            canvas.drawString(18 * mm, y, line)
            y -= 4 * mm
        y -= 3 * mm
    canvas.save()
    return output.getvalue()


@router.post("")
async def export_report(
    request: Request,
    db: MongoDep,
    settings: SettingsDep,
    principal: AnalystDep,
    export_format: str = Query("csv", alias="format", pattern="^(pdf|csv|json)$"),
    intel_ids: list[str] = Query(default=[]),
) -> Response:
    if not intel_ids:
        raise HTTPException(status_code=422, detail="intel_ids is required")
    if len(intel_ids) > MAX_EXPORT_ROWS:
        raise HTTPException(status_code=422, detail="too many intel_ids")
    query = {"intel_id": {"$in": intel_ids}}
    docs = await db.intel.find(query).to_list(length=MAX_EXPORT_ROWS)
    if not docs:
        raise HTTPException(status_code=404, detail="No intelligence records available to export")
    raw_docs = await db.raw_ingest.find(
        {"ingest_id": {"$in": [d.get("ingest_id") for d in docs]}},
        {"ingest_id": 1, "source_ref": 1},
    ).to_list(length=MAX_EXPORT_ROWS)
    source_refs = {str(doc.get("ingest_id")): str(doc.get("source_ref", "")) for doc in raw_docs}
    records = [_flatten_doc(doc, source_refs.get(str(doc.get("ingest_id")), "")) for doc in docs]

    if export_format == "json":
        final = json.dumps({"data": records}, default=str, separators=(",", ":")).encode()
        media_type, filename = "application/json", "darkpulse-export.json"
    elif export_format == "pdf":
        final = await asyncio.to_thread(_pdf_report, records)
        media_type, filename = "application/pdf", "darkpulse-report.pdf"
    else:
        output = io.StringIO()
        writer = csv.DictWriter(
            output, fieldnames=list(records[0].keys()) if records else list(_flatten_doc({}).keys())
        )
        writer.writeheader()
        writer.writerows({key: _csv_cell(value) for key, value in row.items()} for row in records)
        final = output.getvalue().encode()
        media_type, filename = "text/csv", "darkpulse-export.csv"
    await audit_event(
        db,
        request,
        principal,
        "export.create",
        target_type="intel_export",
        metadata={
            "format": export_format,
            "record_count": len(records),
            "seal": sha256_hex(final),
        },
        required=True,
    )
    seal = await generate_seal(final, db, settings)
    await db.export_manifests.update_one(
        {"_id": seal["hash_sha256"]},
        {"$setOnInsert": {
            "hash_sha256": seal["hash_sha256"],
            "sealed_at": seal.get("sealed_at"),
            "format": export_format,
            "intel_ids": [str(r.get("intel_id")) for r in records],
            "exported_by": principal.subject,
            "created_at": datetime.now(UTC),
        }},
        upsert=True,
    )
    return Response(
        content=final,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-DarkPulse-Evidence-Seal": seal["hash_sha256"],
        },
    )


@router.get("/manifest/{seal_hash}")
async def get_manifest(seal_hash: str, db: MongoDep, _: ViewerDep) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{64}", seal_hash):
        raise HTTPException(status_code=422, detail="seal hash must be 64 hex chars")
    doc = await db.export_manifests.find_one({"hash_sha256": seal_hash})
    if not doc:
        raise HTTPException(status_code=404, detail="No export manifest for this seal")
    doc.pop("_id", None)
    return {"data": doc, "meta": {}}
