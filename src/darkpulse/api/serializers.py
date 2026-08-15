from __future__ import annotations

from typing import Any

from darkpulse.models import TraffickingIntel


def serialize_intel(doc: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in doc.items() if key != "_id"}
    snapshot = cleaned.pop("evidence_snapshot", None)
    cleaned.pop("processing", None)
    if "sanitization" not in cleaned or "intent" not in cleaned or "severity" not in cleaned:
        return {**cleaned, **({"evidence_snapshot": snapshot} if snapshot else {})}
    try:
        payload = TraffickingIntel.model_validate(cleaned).model_dump(
            mode="json", by_alias=True
        )
    except Exception:
        payload = cleaned
    if snapshot:
        payload["evidence_snapshot"] = snapshot
    for key in ("intel_id", "ingest_id", "trace_id"):
        if payload.get(key) is not None:
            payload[key] = str(payload[key])
    return payload


def flatten_canonicals(values: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, str):
            value = item.strip()
            if value and value not in seen:
                seen.add(value)
                found.append(value)
            return
        if isinstance(item, dict):
            walk(item.get("canonical") or item.get("name"))
            return
        if isinstance(item, list):
            for child in item:
                walk(child)

    walk(values)
    return found
