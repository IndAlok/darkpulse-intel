from __future__ import annotations

from darkpulse.nlp.language import (
    detect_language_info,
    is_code_mixed,
    is_romanized,
    normalize_text,
    replace_emoji,
)


class TestEmojiReplacement:
    def test_cannabis_emoji(self):
        text = "🍃 available"
        result, had_emoji = replace_emoji(text)
        assert had_emoji
        assert "cannabis" in result.lower()

    def test_multiple_emoji(self):
        text = "🍃 ❄️ 💊"
        result, had_emoji = replace_emoji(text)
        assert had_emoji
        assert "cannabis" in result.lower()
        assert "cocaine" in result.lower()
        assert "pills" in result.lower()

    def test_no_emoji(self):
        text = "plain text"
        result, had_emoji = replace_emoji(text)
        assert not had_emoji
        assert result == text


class TestRomanizationDetection:
    def test_hindi_romanized(self):
        assert is_romanized("kya haal hai bhai")

    def test_gujarati_romanized(self):
        assert is_romanized("shu che bhai")

    def test_english_only(self):
        assert not is_romanized("Hello, how are you?")


class TestCodeMixDetection:
    def test_mixed_script(self):
        _ = is_code_mixed("Hello दुनिया")


class TestNormalization:
    def test_whitespace_normalization(self):
        text = "  hello   world  "
        result = normalize_text(text)
        assert result.text == "hello world"

    def test_emoji_normalization(self):
        text = "🍃 available"
        result = normalize_text(text)
        assert result.emoji_replaced

    def test_leetspeak_normalization(self):
        text = "drvg5"
        result = normalize_text(text)
        assert result.leetspeak_folded or result.text != text


class TestLanguageDetection:
    def test_english_detection(self):
        info = detect_language_info("Hello, this is a test message.")
        assert "en" in info.detected

    def test_returns_language_info(self):
        info = detect_language_info("MDMA pills available. $50 for 10.")
        assert hasattr(info, "detected")
        assert hasattr(info, "code_mixed")
        assert hasattr(info, "romanized")
        assert isinstance(info.detected, list)
