from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yara

from darkpulse.models import Sanitization, SanitizationStatus

logger = logging.getLogger(__name__)

_CSAM_HASH_PREFIXES: set[str] = set()

_ILLEGAL_PATTERNS: list[str] = [
    r"child\s*(?:porn|abuse|exploit)",
    r"(?:underage|minor)\s*(?:sex|porn|nude)",
    r"cp\s*(?:pics|pics|video|trade)",
    r"pedo(?:phile|philia|file)",
    r"child\s*(?:molestation|rape)",
    r"(?:incest|bestiality)\s*(?:porn|video|pic)",
]

_EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_INDIA_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\w)")

_YARA_RULES_SOURCE = """
rule csam_keyword_match {
    meta:
        description = "Matches potential CSAM-related keywords"
        severity = "critical"
        action = "drop"
    strings:
        $cp1 = "child porn" nocase
        $cp2 = "child abuse" nocase
        $cp3 = "underage sex" nocase
        $cp4 = "underage porn" nocase
        $cp5 = "underage nude" nocase
        $cp6 = "pedo" nocase
        $cp7 = "lolita" nocase
        $cp8 = "jailbait" nocase
        $cp9 = "child exploitation" nocase
        $cp10 = "cp pics" nocase
        $cp11 = "cp trade" nocase
    condition:
        any of them
}

rule drug_trafficking_indicators {
    meta:
        description = "Confirms drug trafficking content (not dropped, just flagged)"
        severity = "info"
        action = "flag"
    strings:
        $d1 = "ship worldwide" nocase
        $d2 = "discrete packaging" nocase
        $d3 = "stealth shipping" nocase
        $d4 = "FE only" nocase
        $d5 = "finalized early" nocase
        $d6 = "escrow" nocase
        $d7 = "bulk discount" nocase
        $d8 = "sample available" nocase
    condition:
        2 of them
}
"""


def _compile_yara_rules() -> yara.Rules:
    try:
        return yara.compile(source=_YARA_RULES_SOURCE)
    except yara.Error:
        logger.warning("Failed to compile YARA rules, using empty ruleset")
        return yara.compile(source="rule dummy { condition: false }")


_compiled_rules: yara.Rules | None = None


def _get_rules() -> yara.Rules:
    global _compiled_rules
    if _compiled_rules is None:
        _compiled_rules = _compile_yara_rules()
    return _compiled_rules


@dataclass
class SanitizationResult:
    status: SanitizationStatus
    detectors_fired: list[str] = field(default_factory=list)
    illegal_flag: bool = False
    content_hash: str = ""


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def check_csam_hash(content_hash: str) -> bool:
    hash_prefix = content_hash[:16].lower()
    return hash_prefix in _CSAM_HASH_PREFIXES


def load_csam_blocklist(blocklist_path: Path | str | None = None) -> None:
    global _CSAM_HASH_PREFIXES
    if blocklist_path is None:
        return

    path = Path(blocklist_path)
    if not path.exists():
        logger.warning("CSAM blocklist file not found: %s", path)
        return

    prefixes: set[str] = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                prefixes.add(line[:16].lower())

    _CSAM_HASH_PREFIXES = prefixes
    logger.info("Loaded %d CSAM hash prefixes from %s", len(prefixes), path)


def run_yara_matches(content: str) -> list[str]:
    rules = _get_rules()
    matches = rules.match(data=content.encode("utf-8"))
    return [match.rule for match in matches]


def check_illegal_patterns(content: str) -> bool:
    content_lower = content.lower()
    return any(re.search(pattern, content_lower) for pattern in _ILLEGAL_PATTERNS)


def redact_sensitive_text(content: str) -> tuple[str, list[str]]:
    detectors: list[str] = []
    redacted, email_count = _EMAIL_PATTERN.subn("[EMAIL_REDACTED]", content)
    if email_count:
        detectors.append("pii:email")

    redacted, phone_count = _INDIA_PHONE_PATTERN.subn("[PHONE_REDACTED]", redacted)
    if phone_count:
        detectors.append("pii:phone")
    return redacted, detectors


def sanitize_content(
    content: str,
    content_hash: str | None = None,
) -> Sanitization:
    if content_hash is None:
        content_hash = compute_content_hash(content)

    detectors_fired: list[str] = []
    illegal_flag = False

    if check_csam_hash(content_hash):
        detectors_fired.append("csam_hash_match")
        illegal_flag = True
        logger.critical(
            "CSAM hash match detected — content dropped",
            extra={"content_hash_prefix": content_hash[:16]},
        )
        return Sanitization(
            status=SanitizationStatus.DROPPED,
            detectors_fired=detectors_fired,
            illegal_flag=True,
        )

    yara_matches = run_yara_matches(content)
    for match_name in yara_matches:
        detectors_fired.append(f"yara:{match_name}")
        if match_name == "csam_keyword_match":
            illegal_flag = True
            logger.critical(
                "YARA CSAM keyword match — content dropped",
                extra={"rule": match_name},
            )
            return Sanitization(
                status=SanitizationStatus.DROPPED,
                detectors_fired=detectors_fired,
                illegal_flag=True,
            )

    if check_illegal_patterns(content):
        detectors_fired.append("illegal_pattern_regex")
        illegal_flag = True
        logger.critical("Illegal pattern regex match — content dropped")
        return Sanitization(
            status=SanitizationStatus.DROPPED,
            detectors_fired=detectors_fired,
            illegal_flag=illegal_flag,
        )

    status = SanitizationStatus.SANITIZED if detectors_fired else SanitizationStatus.CLEAN

    return Sanitization(
        status=status,
        detectors_fired=detectors_fired,
        illegal_flag=False,
    )
