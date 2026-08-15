from __future__ import annotations

import json
import re
from typing import Any

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SENSITIVE = re.compile(
    r"(?i)(?:[\w.+-]+@[\w.-]+|(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)|"
    r"0x[a-f0-9]{40}\b|[13][a-km-zA-HJ-NP-Z1-9]{25,34})"
)


def normalize_excerpt(raw: str, *, limit: int = 2000) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text[:1] in "{[":
        extracted = _text_from_json(text)
        if extracted:
            text = extracted
    if "<" in text and ">" in text:
        text = _TAG.sub(" ", text)
    text = _SENSITIVE.sub("[REDACTED]", text)
    text = _WS.sub(" ", text).strip()
    return text[:limit]


def _text_from_json(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    parts: list[str] = []
    _collect_strings(payload, parts)
    return " · ".join(parts[:40])


def _collect_strings(value: Any, parts: list[str]) -> None:
    if len(parts) >= 40:
        return
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned and not cleaned.startswith(("http://", "https://")):
            parts.append(cleaned)
        return
    if isinstance(value, dict):
        for key in ("title", "description", "summary", "text", "content", "headline"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
        for item in value.values():
            _collect_strings(item, parts)
        return
    if isinstance(value, list):
        for item in value[:20]:
            _collect_strings(item, parts)
