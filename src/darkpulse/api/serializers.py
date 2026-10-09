from __future__ import annotations

from typing import Any

from darkpulse.api.excerpts import _SENSITIVE
from darkpulse.models import TraffickingIntel


def serialize_intel(doc: dict[str, Any], *, role: str | None = None) -> dict[str, Any]:
    cleaned = {key: value for key, value in doc.items() if key != "_id"}
    snapshot = cleaned.pop("evidence_snapshot", None)
    cleaned.pop("processing", None)
    payload = cleaned
    if {"sanitization", "intent", "severity"} <= cleaned.keys():
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
    if role == "viewer":
        entities = payload.get("entities")
        if isinstance(entities, dict):
            payload["entities"] = {
                key: value
                for key, value in entities.items()
                if key not in {"crypto_wallets", "contacts", "pgp_fingerprints"}
            }
        payload["actor_links"] = []
        text = payload.get("translated_text")
        if isinstance(text, str):
            payload["translated_text"] = _SENSITIVE.sub("[REDACTED]", text)
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
