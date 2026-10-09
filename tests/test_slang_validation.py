"""Slang entry validation: placeholder meanings and invisible characters (422)."""

import pytest
from pydantic import ValidationError

from darkpulse.models import SlangEntry


def test_placeholder_meaning_rejected() -> None:
    for bad in ["", "  unknown  ", "TBD", "N/A", "placeholder", "TODO", "meaning"]:
        with pytest.raises(ValidationError):
            SlangEntry(term="chitta", meaning=bad)


def test_real_meaning_accepted() -> None:
    entry = SlangEntry(term="chitta", meaning="heroin")
    assert entry.meaning == "heroin"


def test_zero_width_term_rejected() -> None:
    with pytest.raises(ValidationError):
        SlangEntry(term="cha\u200bras", meaning="cannabis resin")


def test_control_char_term_rejected() -> None:
    with pytest.raises(ValidationError):
        SlangEntry(term="cha\x01ras", meaning="cannabis resin")


def test_clean_term_accepted() -> None:
    assert SlangEntry(term="charas", meaning="cannabis resin").term == "charas"


def test_decode_text_ignores_zero_width_inside_word() -> None:
    from pathlib import Path

    from darkpulse.nlp.slang import SlangDictionary

    d = SlangDictionary()
    loaded = d.load_seed(Path("data/slang_dictionary/seed_dictionary.txt"))
    assert loaded > 0
    decoded = d.decode_text("selling cha\u200bras today")
    assert any(m["term"] == "charas" for m in decoded), decoded
