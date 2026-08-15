from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_INTEL_ID = re.compile(
    r"^(?:intel:)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{12,64})$",
    re.I,
)

_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "weed": ("weed", "cannabis", "marijuana", "ganja", "pot", "kush", "w33d"),
    "cannabis": ("weed", "cannabis", "marijuana", "ganja", "pot", "kush"),
    "marijuana": ("weed", "cannabis", "marijuana", "ganja"),
    "ganja": ("weed", "cannabis", "ganja", "bhang"),
    "heroin": ("heroin", "smack", "brown sugar"),
    "cocaine": ("cocaine", "coke"),
    "mdma": ("mdma", "ecstasy", "molly"),
    "meth": ("meth", "methamphetamine", "ice"),
}

_SEED_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "data" / "slang_dictionary" / "seed_dictionary.txt",
    Path("/app/data/slang_dictionary/seed_dictionary.txt"),
)


def extract_intel_id(query: str) -> str | None:
    match = _INTEL_ID.fullmatch(query.strip())
    if not match:
        return None
    return match.group(1)


def intel_id_candidates(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    values = [text]
    if text.lower().startswith("intel:"):
        values.append(text.split(":", 1)[1].strip())
    extracted = extract_intel_id(text)
    if extracted:
        values.append(extracted)
        values.append(extracted.replace("-", ""))
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


@lru_cache(maxsize=1)
def _seed_aliases() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, set[str]] = {key: set(values) for key, values in _TERM_ALIASES.items()}
    try:
        from darkpulse.nlp.slang import SlangDictionary
    except Exception:
        return {key: tuple(sorted(values)) for key, values in aliases.items()}

    dictionary = SlangDictionary()
    for path in _SEED_CANDIDATES:
        if path.is_file():
            dictionary.load_seed(path)
            break
    if dictionary.size == 0:
        return {key: tuple(sorted(values)) for key, values in aliases.items()}

    for entry in dictionary.get_all_entries():
        term = str(entry.get("term") or "").strip().casefold()
        meaning = str(entry.get("canonical") or "").strip()
        if not term or not meaning:
            continue
        meaning_key = meaning.casefold()
        head = re.split(r"[^a-z0-9]+", meaning_key, maxsplit=1)[0]
        for key in {term, meaning_key, head}:
            if len(key) < 2:
                continue
            bucket = aliases.setdefault(key, set())
            bucket.update({term, meaning_key})
            if head and len(head) >= 3:
                bucket.add(head)
    return {key: tuple(sorted(values)) for key, values in aliases.items()}


def expand_search_terms(query: str) -> list[str]:
    terms = [query.strip()]
    aliases = _seed_aliases()
    for token in re.findall(r"[a-zA-Z0-9]{2,32}", query.lower()):
        terms.append(token)
        terms.extend(aliases.get(token, ()))
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:16]
