from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_QUERY_PARTS = (
    "access",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "key",
    "password",
    "secret",
    "session",
    "signature",
    "token",
)


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sanitize_source_ref(source_ref: str) -> str:
    source_ref = source_ref.strip()
    try:
        parsed = urlsplit(source_ref)
    except ValueError:
        return f"invalid-ref://sha256/{sha256_hex(source_ref.encode('utf-8'))}"
    if not parsed.scheme:
        return source_ref[:2048]

    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        return f"invalid-ref://sha256/{sha256_hex(source_ref.encode('utf-8'))}"
    if port is not None:
        hostname = f"{hostname}:{port}"

    safe_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if any(
            lowered == part or lowered.startswith(f"{part}_") or lowered.endswith(f"_{part}")
            for part in SENSITIVE_QUERY_PARTS
        ):
            continue
        safe_query.append((key, value))

    sanitized = urlunsplit(
        (
            parsed.scheme.casefold(),
            hostname,
            parsed.path,
            urlencode(sorted(safe_query)),
            "",
        )
    )
    return sanitized[:2048]


def source_ref_fingerprint(source_ref: str) -> str:
    return sha256_hex(source_ref.encode("utf-8"))


def derive_dedup_key(
    *,
    source_class: str,
    source_ref: str,
    content_sha256: str,
) -> str:
    identity = canonical_json_bytes(
        {
            "content_sha256": content_sha256,
            "source_class": source_class,
            "source_ref": source_ref,
        }
    )
    return f"sha256:{sha256_hex(identity)}"
