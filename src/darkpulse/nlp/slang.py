from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


@dataclass
class SlangEntry:
    term: str
    canonical: str
    language: str
    category: str = "general"
    confidence: float = 0.9
    source: str = "manual"
    approved: bool = True
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "canonical": self.canonical,
            "language": self.language,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "approved": self.approved,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlangEntry:
        return cls(
            term=data["term"],
            canonical=data["canonical"],
            language=data["language"],
            category=data.get("category", "general"),
            confidence=data.get("confidence", 0.9),
            source=data.get("source", "manual"),
            approved=data.get("approved", True),
            context=data.get("context", ""),
        )


@dataclass
class SlangMatch:
    entry: SlangEntry
    score: float
    match_type: str

    @property
    def is_high_confidence(self) -> bool:
        return self.score >= 85

    @property
    def is_candidate(self) -> bool:
        return 60 <= self.score < 85


class SlangDictionary:
    def __init__(self) -> None:
        self._entries: dict[str, SlangEntry] = {}
        self._canonical_index: dict[str, list[str]] = {}
        self._fuzzy_cache: dict[str, list[SlangMatch]] = {}

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def terms(self) -> list[str]:
        return list(self._entries.keys())

    @property
    def canonicals(self) -> list[str]:
        return list(self._canonical_index.keys())

    def load_seed(self, path: Path | str) -> int:
        path = Path(path)
        if not path.exists():
            logger.warning("Seed dictionary not found: %s", path)
            return 0

        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    term = parts[0].lower()
                    canonical = parts[1]
                    language = parts[2]
                    source = parts[3] if len(parts) > 3 else "seed"

                    entry = SlangEntry(
                        term=term,
                        canonical=canonical,
                        language=language,
                        source=source,
                    )
                    self.add_entry(entry)
                    count += 1

        logger.info("Loaded %d entries from seed dictionary %s", count, path)
        return count

    def add_entry(self, entry: SlangEntry) -> None:
        term_lower = entry.term.lower()

        if term_lower in self._entries:
            existing = self._entries[term_lower]
            if existing.canonical != entry.canonical:
                logger.warning(
                    "Overwriting slang entry '%s': '%s' -> '%s'",
                    term_lower,
                    existing.canonical,
                    entry.canonical,
                )

        self._entries[term_lower] = entry

        canonical_lower = entry.canonical.lower()
        if canonical_lower not in self._canonical_index:
            self._canonical_index[canonical_lower] = []
        if term_lower not in self._canonical_index[canonical_lower]:
            self._canonical_index[canonical_lower].append(term_lower)

        self._fuzzy_cache.clear()

    def remove_entry(self, term: str) -> bool:
        term_lower = term.lower()
        entry = self._entries.pop(term_lower, None)
        if entry is None:
            return False

        canonical_lower = entry.canonical.lower()
        if canonical_lower in self._canonical_index:
            self._canonical_index[canonical_lower] = [
                t for t in self._canonical_index[canonical_lower] if t != term_lower
            ]
            if not self._canonical_index[canonical_lower]:
                del self._canonical_index[canonical_lower]

        self._fuzzy_cache.clear()
        return True

    def get_entry(self, term: str) -> SlangEntry | None:
        return self._entries.get(term.lower())

    def lookup(self, term: str) -> SlangMatch | None:
        entry = self.get_entry(term)
        if entry is not None:
            return SlangMatch(entry=entry, score=100.0, match_type="exact")
        return None

    def fuzzy_lookup(
        self,
        term: str,
        threshold: float = 60.0,
        limit: int = 5,
    ) -> list[SlangMatch]:
        term_lower = term.lower()

        if term_lower in self._fuzzy_cache:
            return [m for m in self._fuzzy_cache[term_lower] if m.score >= threshold][:limit]

        exact = self.lookup(term)
        if exact is not None:
            return [exact]

        if not self._entries:
            return []

        all_terms = list(self._entries.keys())
        results = process.extract(
            term_lower,
            all_terms,
            scorer=fuzz.WRatio,
            limit=limit,
        )

        matches = []
        for matched_term, score, _ in results:
            if score >= threshold:
                entry = self._entries[matched_term]
                match_type = "fuzzy"
                if matched_term.startswith(term_lower) or term_lower.startswith(matched_term):
                    match_type = "prefix"

                matches.append(
                    SlangMatch(
                        entry=entry,
                        score=score,
                        match_type=match_type,
                    )
                )

        self._fuzzy_cache[term_lower] = matches

        return matches

    def decode_text(
        self,
        text: str,
        fuzzy_threshold: float = 75.0,
    ) -> list[dict[str, Any]]:
        import re

        decoded: list[dict[str, Any]] = []
        seen_terms: set[str] = set()

        text_lower = text.lower()

        from darkpulse.nlp.language import EMOJI_MAP

        for emoji_char in EMOJI_MAP:
            if emoji_char in text:
                key = f"emoji:{emoji_char}"
                if key in seen_terms:
                    continue
                seen_terms.add(key)
                entry = self.get_entry(emoji_char)
                if entry:
                    decoded.append(
                        {
                            "term": emoji_char,
                            "meaning": entry.canonical,
                            "lang": "emoji",
                            "confidence": 0.9,
                            "newly_discovered": False,
                            "position": text.index(emoji_char),
                        }
                    )

        words = re.findall(r"[\w\u0900-\u097F\u0A80-\u0AFF]+", text_lower)
        for n in range(4, 1, -1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i : i + n])
                if phrase in seen_terms:
                    continue

                entry = self.get_entry(phrase)
                if entry:
                    seen_terms.add(phrase)
                    decoded.append(
                        {
                            "term": phrase,
                            "meaning": entry.canonical,
                            "lang": entry.language,
                            "confidence": 0.95,
                            "newly_discovered": False,
                            "position": text_lower.find(phrase),
                        }
                    )

        for word in words:
            if word in seen_terms:
                continue

            entry = self.get_entry(word)
            if entry:
                seen_terms.add(word)
                decoded.append(
                    {
                        "term": word,
                        "meaning": entry.canonical,
                        "lang": entry.language,
                        "confidence": 0.95,
                        "newly_discovered": False,
                        "position": text_lower.find(word),
                    }
                )
                continue

            if len(word) >= 4:
                matches = self.fuzzy_lookup(word, threshold=fuzzy_threshold, limit=1)
                if matches and matches[0].score >= max(fuzzy_threshold, 85.0):
                    match = matches[0]
                    seen_terms.add(word)
                    decoded.append(
                        {
                            "term": word,
                            "meaning": match.entry.canonical,
                            "lang": match.entry.language,
                            "confidence": match.score / 100.0,
                            "newly_discovered": False,
                            "position": text_lower.find(word),
                        }
                    )

        decoded.sort(key=lambda x: x.get("position", 0))
        return decoded

    def get_all_entries(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._entries.values()]

    def get_entries_by_language(self, language: str) -> list[SlangEntry]:
        return [e for e in self._entries.values() if e.language == language]

    def get_entries_by_canonical(self, canonical: str) -> list[SlangEntry]:
        canonical_lower = canonical.lower()
        terms = self._canonical_index.get(canonical_lower, [])
        return [self._entries[t] for t in terms if t in self._entries]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results = []

        for entry in self._entries.values():
            if (
                query_lower in entry.term.lower()
                or query_lower in entry.canonical.lower()
                or query_lower in entry.context.lower()
            ):
                results.append(entry.to_dict())
                if len(results) >= limit:
                    break

        return results

    def update_entry(self, term: str, updates: dict[str, Any]) -> bool:
        entry = self.get_entry(term)
        if entry is None:
            return False

        for key, value in updates.items():
            if hasattr(entry, key) and key != "term":
                setattr(entry, key, value)

        self.add_entry(entry)
        return True
