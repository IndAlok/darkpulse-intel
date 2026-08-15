import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep, SettingsDep
from darkpulse.api.routes.evidence import generate_seal
from darkpulse.api.security import AnalystDep

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
        "evidence_ref": doc.get("evidence_ref", ""),
        "source_ref": source_ref,
    }


def _pdf_report(records: list[dict[str, Any]], manifest: dict[str, Any] | None = None) -> bytes:
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
            f"{str(record.get('severity_band') or 'info').upper()}  "
            f"{record.get('intent_label') or 'unknown'}  "
            f"{record.get('neighborhood') or 'Location pending'}",
        )
        y -= 5 * mm
        canvas.setFont("Helvetica", 8)
        for line in (
            f"Intel ID: {record.get('intel_id') or 'unknown'}",
            f"Products: {record.get('products') or 'Unspecified'}",
            f"Vendors: {record.get('vendor_aliases') or 'None identified'}",
            f"Source: {record.get('source_class') or 'unknown'}  "
            f"Confidence: {record.get('confidence') or '—'}",
        ):
            if stringWidth(line, "Helvetica", 8) > width - 36 * mm:
                line = line[:110] + "…"
            canvas.drawString(18 * mm, y, line)
            y -= 4 * mm
        y -= 3 * mm
    if manifest:
        y -= 6 * mm
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18 * mm, y, "--- EVIDENCE SEAL ---")
        y -= 5 * mm
        canvas.setFont("Helvetica", 8)
        for key in ("hash_sha256", "provenance", "sealed_at", "tsa_verified", "previous_hash"):
            value = manifest.get(key)
            if value is not None:
                canvas.drawString(18 * mm, y, f"{key}: {value}")
                y -= 5 * mm
                if y < 20 * mm:
                    canvas.showPage()
                    canvas.setFont("Helvetica", 8)
                    y = height - 20 * mm
        canvas.setSubject(f"DarkPulse Evidence Seal {manifest.get('hash_sha256', '')}")
    canvas.save()
    return output.getvalue()


@router.get("")
async def export_report(
    request: Request,
    db: MongoDep,
    settings: SettingsDep,
    principal: AnalystDep,
    export_format: str = Query("csv", alias="format", pattern="^(pdf|csv|json)$"),
    intel_ids: list[str] = Query(default=[]),
) -> Response:
    query = {"intel_id": {"$in": intel_ids}} if intel_ids else {}
    docs = await db.intel.find(query).to_list(length=MAX_EXPORT_ROWS)
    if not docs:
        raise HTTPException(status_code=404, detail="No intelligence records available to export")
    raw_docs = await db.raw_ingest.find(
        {"ingest_id": {"$in": [d.get("ingest_id") for d in docs]}}
    ).to_list(length=MAX_EXPORT_ROWS)
    source_refs = {str(doc.get("ingest_id")): str(doc.get("source_ref", "")) for doc in raw_docs}
    records = [_flatten_doc(doc, source_refs.get(str(doc.get("ingest_id")), "")) for doc in docs]

    if export_format == "json":
        payload = json.dumps({"data": records}, default=str, separators=(",", ":")).encode()
        seal = await generate_seal(payload, db, settings)
        final = json.dumps({"data": records, "evidence_seal": seal}, default=str).encode()
        media_type, filename = "application/json", "darkpulse-export.json"
    elif export_format == "pdf":
        payload = _pdf_report(records)
        seal = await generate_seal(payload, db, settings)
        final, media_type, filename = (
            _pdf_report(records, seal),
            "application/pdf",
            "darkpulse-report.pdf",
        )
    else:
        output = io.StringIO()
        writer = csv.DictWriter(
            output, fieldnames=list(records[0].keys()) if records else list(_flatten_doc({}).keys())
        )
        writer.writeheader()
        writer.writerows(records)
        payload = output.getvalue().encode()
        seal = await generate_seal(payload, db, settings)
        writer.writerow(
            {
                "intel_id": "--- EVIDENCE SEAL ---",
                "content_hash": seal["hash_sha256"],
                "evidence_ref": seal["provenance"],
            }
        )
        final, media_type, filename = output.getvalue().encode(), "text/csv", "darkpulse-export.csv"

    await audit_event(
        db,
        request,
        principal,
        "export.create",
        target_type="intel_export",
        metadata={
            "format": export_format,
            "record_count": len(records),
            "seal": seal["hash_sha256"],
        },
    )
    return Response(
        content=final,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-DarkPulse-Evidence-Seal": seal["hash_sha256"],
        },
    )
