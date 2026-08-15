from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from darkpulse.models import LanguageInfo

logger = logging.getLogger(__name__)

try:
    import fasttext

    _FASTTEXT_AVAILABLE = True
except ImportError:
    _FASTTEXT_AVAILABLE = False
    logger.warning("fasttext not available — language detection will use langdetect only")

_fasttext_model = None

_LANG_CODE_MAP = {
    "__label__en": "en",
    "__label__hi": "hi",
    "__label__gu": "gu",
    "__label__mr": "mr",
    "__label__pa": "pa",
    "__label__bn": "bn",
    "__label__ta": "ta",
    "__label__te": "te",
    "__label__kn": "kn",
    "__label__ml": "ml",
    "__label__ur": "ur",
    "__label__ar": "ar",
    "__label__ne": "ne",
    "__label__si": "si",
}

EMOJI_MAP: dict[str, str] = {
    "\U0001f343": "cannabis",
    "\u2744\ufe0f": "cocaine",
    "\U0001f48a": "pills",
    "\U0001f344": "mushrooms",
    "\U0001f50c": "dealer",
    "\U0001f33f": "cannabis",
    "\U0001f48e": "crystal",
    "\U0001f36b": "hash",
    "\U0001f9ea": "chemical",
    "\U0001f489": "injectable",
    "\U0001f4a8": "smoking",
    "\U0001f9ca": "ice",
}

LEET_MAP: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
    "@": "a",
    "$": "s",
    "!": "i",
    "+": "t",
}

_ROMANIZED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:hai|nahi|kya|kyu|kaun|kaise|kab|kahan)\b", re.I),
    re.compile(r"\b(?:che|nathi|kem|shu|kya|kyare)\b", re.I),
    re.compile(r"\b(?:bahut|accha|theek|chal|yaar|bhai|dost)\b", re.I),
    re.compile(r"\b(?:kaam|maal|saman|rate|delivery|number)\b", re.I),
]

_CODE_MIX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[a-zA-Z]+[\u0900-\u097F]+"),
    re.compile(r"[\u0900-\u097F]+[a-zA-Z]+"),
    re.compile(r"[a-zA-Z]+[\u0A80-\u0AFF]+"),
    re.compile(r"[\u0A80-\u0AFF]+[a-zA-Z]+"),
]


@dataclass
class NormalizedText:
    text: str
    original: str
    emoji_replaced: bool = False
    leetspeak_folded: bool = False
    whitespace_normalized: bool = False


def load_fasttext_model(model_path: str | Path | None = None) -> Any:
    global _fasttext_model
    if _fasttext_model is not None:
        return _fasttext_model

    if not _FASTTEXT_AVAILABLE:
        logger.debug("fasttext module not available")
        return None

    if model_path is None:
        return None

    path = Path(model_path)
    if not path.exists():
        logger.warning(
            "fastText model not found at %s — using langdetect fallback",
            path,
        )
        return None

    try:
        _fasttext_model = fasttext.load_model(str(path))
        logger.info("Loaded fastText model from %s", path)
        return _fasttext_model
    except Exception:
        logger.exception("Failed to load fastText model from %s", path)
        return None


def detect_language_fasttext(text: str, model: Any = None) -> list[tuple[str, float]]:
    if model is None:
        model = _fasttext_model

    if model is None:
        return []

    clean_text = text.replace("\n", " ").strip()
    if not clean_text:
        return []

    try:
        predictions = model.predict(clean_text, k=5)
    except Exception:
        logger.warning("fasttext predict failed for %d chars", len(clean_text))
        return []
    results = []
    for label, score in zip(predictions[0], predictions[1], strict=False):
        lang_code = _LANG_CODE_MAP.get(label, label.replace("__label__", ""))
        results.append((lang_code, float(score)))

    return results


def detect_language_langdetect(text: str) -> tuple[str, float] | None:
    try:
        from langdetect import detect_langs

        results = detect_langs(text)
        if results:
            best = results[0]
            return (best.lang, best.prob)
    except Exception:
        logger.debug("langdetect failed for text snippet")

    return None


def is_romanized(text: str) -> bool:
    return any(pattern.search(text) for pattern in _ROMANIZED_PATTERNS)


def is_code_mixed(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CODE_MIX_PATTERNS)


def replace_emoji(text: str, emoji_map: dict[str, str] | None = None) -> tuple[str, bool]:
    if emoji_map is None:
        emoji_map = EMOJI_MAP

    had_emoji = False
    result = text
    for emoji_char, replacement in emoji_map.items():
        if emoji_char in result:
            result = result.replace(emoji_char, f" {replacement} ")
            had_emoji = True

    return result, had_emoji


def fold_leetspeak(text: str) -> tuple[str, bool]:
    had_leetspeak = False
    result = list(text)

    for i, char in enumerate(result):
        if char in LEET_MAP:
            result[i] = LEET_MAP[char]
            had_leetspeak = True

    return "".join(result), had_leetspeak


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_text(text: str) -> NormalizedText:
    original = text

    text = unicodedata.normalize("NFKC", text)

    text, emoji_replaced = replace_emoji(text)

    text, leetspeak_folded = fold_leetspeak(text)

    text = normalize_whitespace(text)
    whitespace_normalized = text != original

    return NormalizedText(
        text=text,
        original=original,
        emoji_replaced=emoji_replaced,
        leetspeak_folded=leetspeak_folded,
        whitespace_normalized=whitespace_normalized,
    )


def detect_language_info(text: str) -> LanguageInfo:
    fasttext_results = detect_language_fasttext(text)

    detected: list[str] = []
    if fasttext_results:
        detected = [lang for lang, _ in fasttext_results[:3]]
    else:
        fallback = detect_language_langdetect(text)
        if fallback is not None:
            detected = [fallback[0]]

    code_mixed = is_code_mixed(text)

    romanized = is_romanized(text)

    if code_mixed and len(detected) == 1:
        if detected[0] == "en":
            detected.append("hi")
        elif detected[0] in ("hi", "gu"):
            detected.append("en")

    return LanguageInfo(
        detected=detected,
        code_mixed=code_mixed,
        romanized=romanized,
    )
