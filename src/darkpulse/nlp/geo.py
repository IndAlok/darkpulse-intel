from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from darkpulse.models import GeoBasis, GeoLocation

logger = logging.getLogger(__name__)

SURAT_NEIGHBORHOODS: dict[str, dict[str, Any]] = {
    "adajan": {"aliases": ["adajan patia", "adajan gate", "adajan road"], "area": "west"},
    "varachha": {"aliases": ["varachha road", "varachha main road"], "area": "central"},
    "katargam": {"aliases": ["katargam darwaja", "katargam gate"], "area": "central"},
    "udhna": {"aliases": ["udhna gate", "udhna darwaja", "udhna station"], "area": "south"},
    "piplod": {"aliases": ["piplod circle", "dumas road piplod"], "area": "west"},
    "rander": {"aliases": ["rander road", "rander patia"], "area": "north"},
    "athwa": {"aliases": ["athwa gate", "athwa lines"], "area": "central"},
    "vesu": {"aliases": ["vesu main road", "vesu patia"], "area": "west"},
    "dumas": {"aliases": ["dumas road", "dumas beach"], "area": "west"},
    "pal": {"aliases": ["pal gam", "pal road"], "area": "west"},
    "godadara": {"aliases": ["godadara road"], "area": "north"},
    "bamroli": {"aliases": ["bamroli road"], "area": "north"},
    "puna": {"aliases": ["puna gam", "puna patia"], "area": "south"},
    "magob": {"aliases": ["magob patia", "magob road"], "area": "north"},
    "limbayat": {"aliases": ["limbayat area"], "area": "south"},
    "sarthana": {"aliases": ["sarthana jakatnaka", "sarthana gate"], "area": "east"},
    "textile": {"aliases": ["textile market", "ring road textile"], "area": "central"},
    "station": {"aliases": ["surat station", "railway station", "stn"], "area": "central"},
    "ringroad": {"aliases": ["ring road", "ring road surat"], "area": "central"},
    "citylight": {"aliases": ["city light", "city light road"], "area": "west"},
    "ghod dod": {"aliases": ["ghod dod road", "ghoddod"], "area": "central"},
    "bhatar": {"aliases": ["bhatar road", "bhatar char rasta"], "area": "west"},
    "majura": {"aliases": ["majura gate", "majura gate surat"], "area": "central"},
    "rustampura": {"aliases": ["rustampura main road"], "area": "central"},
    "nanpura": {"aliases": ["nanpura main road"], "area": "central"},
    "sagrampura": {"aliases": ["sagrampura main road"], "area": "central"},
    "begampura": {"aliases": ["begampura main road"], "area": "central"},
    "chowk": {"aliases": ["chowk bazar", "chowk area"], "area": "central"},
    "makaipul": {"aliases": ["makaipul road"], "area": "central"},
    "punagam": {"aliases": ["punagam main road"], "area": "south"},
    "vedroad": {"aliases": ["ved road", "ved road surat"], "area": "central"},
    "kapodra": {"aliases": ["kapodra area", "kapodra road"], "area": "east"},
    "parvat": {"aliases": ["parvat patia", "parvat road"], "area": "east"},
    "yogi chowk": {"aliases": ["yogi chowk area"], "area": "east"},
    "dindoli": {"aliases": ["dindoli area"], "area": "south"},
    "sachin": {"aliases": ["sachin gam", "sachin area"], "area": "south"},
    "hazira": {"aliases": ["hazira road", "hazira industrial"], "area": "south"},
    "ichchapor": {"aliases": ["ichchapor village"], "area": "south"},
    "olpad": {"aliases": ["olpad area", "olpad road"], "area": "north"},
    "bardoli": {"aliases": ["bardoli road"], "area": "east"},
    "kamrej": {"aliases": ["kamrej char rasta", "kamrej road"], "area": "east"},
    "navsari": {"aliases": ["navsari road"], "area": "south"},
    "vyara": {"aliases": ["vyara road"], "area": "east"},
    "mandvi": {"aliases": ["mandvi area"], "area": "central"},
}

_LOCATION_SLANG: dict[str, str] = {
    "surat special": "surat",
    "city delivery": "surat",
}

_SHIP_FROM_PATTERNS = [
    re.compile(r"(?:ship(?:ped)?\s+from|ships?\s+from|location)\s*:\s*(.+?)(?:\n|$)", re.I),
    re.compile(r"(?:origin|dispatch(?:ed)?|sent\s+from)\s*:\s*(.+?)(?:\n|$)", re.I),
    re.compile(r"(?:based\s+in|located\s+in)\s*:\s*(.+?)(?:\n|$)", re.I),
]


@dataclass
class GeoMatchResult:
    geo: GeoLocation
    matched_terms: list[str]
    confidence_breakdown: dict[str, float]


def _build_match_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, data in SURAT_NEIGHBORHOODS.items():
        index[canonical.lower()] = canonical
        for alias in data.get("aliases", []):
            index[alias.lower()] = canonical
    return index


_MATCH_INDEX: dict[str, str] | None = None


def _get_match_index() -> dict[str, str]:
    global _MATCH_INDEX
    if _MATCH_INDEX is None:
        _MATCH_INDEX = _build_match_index()
    return _MATCH_INDEX


def resolve_neighborhood_names(raw: str) -> list[str]:
    needle = raw.strip()
    if not needle:
        return []
    names = {needle, needle.casefold()}
    canonical = _get_match_index().get(needle.casefold())
    if canonical:
        names.add(canonical)
        names.add(canonical.casefold())
        names.add(canonical.title())
        for alias in SURAT_NEIGHBORHOODS.get(canonical, {}).get("aliases", []):
            names.add(str(alias))
            names.add(str(alias).casefold())
    return sorted(names)


def match_explicit(text: str) -> tuple[str | None, float, list[str]]:
    index = _get_match_index()
    text_lower = text.lower()

    matches: list[tuple[str, str]] = []

    sorted_terms = sorted(index.keys(), key=len, reverse=True)

    for term in sorted_terms:
        canonical = index[term]
        if len(term) <= 4:
            pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.I)
            if pattern.search(text_lower):
                matches.append((canonical, term))
        else:
            if term in text_lower:
                matches.append((canonical, term))

    if not matches:
        return (None, 0.0, [])

    best = max(matches, key=lambda m: len(m[1]))
    matched_terms = list({m[1] for m in matches})

    confidence = min(0.95, 0.7 + len(best[1]) * 0.02)

    return (best[0], confidence, matched_terms)


def match_slang(text: str) -> tuple[str | None, float, list[str]]:
    text_lower = text.lower()
    matched_terms: list[str] = []

    for slang, _ in _LOCATION_SLANG.items():
        if slang in text_lower:
            matched_terms.append(slang)

    if not matched_terms:
        return (None, 0.0, [])

    confidence = 0.8 if "surat special" in matched_terms else 0.55

    return ("surat", confidence, matched_terms)


def match_ship_from(text: str) -> tuple[str | None, float, list[str]]:
    index = _get_match_index()
    matched_terms: list[str] = []

    for pattern in _SHIP_FROM_PATTERNS:
        for match in pattern.finditer(text):
            location_str = match.group(1).strip().lower()
            matched_terms.append(location_str)

            for term, canonical in index.items():
                if term in location_str:
                    return (canonical, 0.85, matched_terms)

            if "surat" in location_str:
                return ("surat", 0.8, matched_terms)

    return (None, 0.0, matched_terms)


def match_geo(
    text: str,
    source_class: str = "",
    geo_hints: list[str] | None = None,
) -> GeoLocation:
    neighborhood, confidence, terms = match_explicit(text)
    if neighborhood and confidence >= 0.7:
        return GeoLocation(
            neighborhood=neighborhood,
            city="Surat",
            confidence=confidence,
            basis=GeoBasis.EXPLICIT,
        )

    location, ship_confidence, ship_terms = match_ship_from(text)
    if location and ship_confidence >= 0.7:
        if location in SURAT_NEIGHBORHOODS:
            return GeoLocation(
                neighborhood=location,
                city="Surat",
                confidence=ship_confidence,
                basis=GeoBasis.SHIP_FROM,
            )
        return GeoLocation(
            neighborhood="",
            city="Surat",
            confidence=ship_confidence,
            basis=GeoBasis.SHIP_FROM,
        )

    city, slang_confidence, slang_terms = match_slang(text)
    if city and slang_confidence >= 0.5:
        return GeoLocation(
            neighborhood="",
            city="Surat",
            confidence=slang_confidence,
            basis=GeoBasis.SLANG,
        )

    if geo_hints:
        for hint in geo_hints:
            hint_lower = hint.lower()
            index = _get_match_index()
            for term, canonical in index.items():
                if term in hint_lower:
                    return GeoLocation(
                        neighborhood=canonical,
                        city="Surat",
                        confidence=0.6,
                        basis=GeoBasis.INFERENCE,
                    )
            if "surat" in hint_lower:
                return GeoLocation(
                    neighborhood="",
                    city="Surat",
                    confidence=0.5,
                    basis=GeoBasis.INFERENCE,
                )

    return GeoLocation(
        neighborhood="",
        city="",
        confidence=0.0,
        basis=GeoBasis.INFERENCE,
    )
