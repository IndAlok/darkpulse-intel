from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType


class RejectReason(StrEnum):
    CONTENT_TYPE_NOT_ALLOWED = "content_type_not_allowed"
    MIME_TYPE_NOT_ALLOWED = "mime_type_not_allowed"
    SOURCE_TOO_LARGE = "source_too_large"
    CONTENT_TOO_LARGE = "content_too_large"
    SOURCE_BLOCKED = "source_blocked"
    SOURCE_HASH_BLOCKED = "source_hash_blocked"
    CONTENT_HASH_BLOCKED = "content_hash_blocked"
    BINARY_CONTROL_CHARACTER = "binary_control_character"


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    accepted: bool
    policy_version: str
    checks: tuple[str, ...]
    reasons: tuple[RejectReason, ...] = ()


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    policy_version: str
    max_source_bytes: int
    max_content_bytes: int
    allowed_content_types: frozenset[ContentType]
    allowed_mime_types: frozenset[str]
    blocked_source_prefixes: tuple[str, ...]
    blocked_source_sha256: frozenset[str]
    blocked_content_sha256: frozenset[str]

    @classmethod
    def from_path(cls, path: Path) -> SafetyPolicy:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            policy_version=str(raw["policy_version"]),
            max_source_bytes=int(raw["max_source_bytes"]),
            max_content_bytes=int(raw["max_content_bytes"]),
            allowed_content_types=frozenset(
                ContentType(item) for item in raw["allowed_content_types"]
            ),
            allowed_mime_types=frozenset(
                str(item).casefold() for item in raw["allowed_mime_types"]
            ),
            blocked_source_prefixes=tuple(
                str(item) for item in raw.get("blocked_source_prefixes", [])
            ),
            blocked_source_sha256=frozenset(
                str(item).casefold() for item in raw.get("blocked_source_sha256", [])
            ),
            blocked_content_sha256=frozenset(
                str(item).casefold() for item in raw.get("blocked_content_sha256", [])
            ),
        )

    def evaluate(
        self,
        record: SourceRecord,
        *,
        source_sha256: str,
        content_bytes: bytes,
        content_sha256: str,
    ) -> SafetyDecision:
        reasons: list[RejectReason] = []
        mime_type = record.mime_type.split(";", maxsplit=1)[0].strip().casefold()

        if record.content_type not in self.allowed_content_types:
            reasons.append(RejectReason.CONTENT_TYPE_NOT_ALLOWED)
        if mime_type not in self.allowed_mime_types:
            reasons.append(RejectReason.MIME_TYPE_NOT_ALLOWED)
        if len(record.source_bytes) > self.max_source_bytes:
            reasons.append(RejectReason.SOURCE_TOO_LARGE)
        if len(content_bytes) > self.max_content_bytes:
            reasons.append(RejectReason.CONTENT_TOO_LARGE)
        if any(record.source_ref.startswith(prefix) for prefix in self.blocked_source_prefixes):
            reasons.append(RejectReason.SOURCE_BLOCKED)
        if source_sha256.casefold() in self.blocked_source_sha256:
            reasons.append(RejectReason.SOURCE_HASH_BLOCKED)
        if content_sha256.casefold() in self.blocked_content_sha256:
            reasons.append(RejectReason.CONTENT_HASH_BLOCKED)
        if any(ord(char) < 32 and char not in "\t\n\r" for char in record.raw_content):
            reasons.append(RejectReason.BINARY_CONTROL_CHARACTER)

        checks = (
            "content_type:text_only",
            "mime_type:allowlist",
            "size_limits",
            "source_policy",
            "blocked_source_hash",
            "blocked_content_hash",
            "binary_persistence:false",
        )
        return SafetyDecision(
            accepted=not reasons,
            policy_version=self.policy_version,
            checks=checks,
            reasons=tuple(dict.fromkeys(reasons)),
        )
