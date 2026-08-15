from __future__ import annotations

from pathlib import Path
from typing import Any

from darkpulse.nlp.slang import SlangDictionary, SlangEntry


def build_runtime_dictionary(
    seed_path: Path | str, entries: list[dict[str, Any]]
) -> SlangDictionary:
    dictionary = SlangDictionary()
    dictionary.load_seed(seed_path)
    for entry in entries:
        if entry.get("review_status", "approved") != "approved":
            continue
        dictionary.add_entry(
            SlangEntry(
                term=str(entry["term"]),
                canonical=str(entry["meaning"]),
                language=str(entry.get("lang", "en")),
                confidence=float(entry.get("confidence", 1.0)),
                source="analyst",
                approved=True,
            )
        )
    return dictionary
