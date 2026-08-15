from __future__ import annotations

from darkpulse.models import SanitizationStatus
from darkpulse.nlp.sanitizer import (
    check_csam_hash,
    compute_content_hash,
    sanitize_content,
)


class TestContentHash:
    def test_hash_consistency(self):
        text = "test content"
        hash1 = compute_content_hash(text)
        hash2 = compute_content_hash(text)
        assert hash1 == hash2

    def test_hash_format(self):
        hash_val = compute_content_hash("test")
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_different_inputs_different_hashes(self):
        hash1 = compute_content_hash("content 1")
        hash2 = compute_content_hash("content 2")
        assert hash1 != hash2


class TestCSAMHashCheck:
    def test_unknown_hash_passes(self):
        hash_val = compute_content_hash("legitimate content")
        assert not check_csam_hash(hash_val)


class TestSanitization:
    def test_clean_content(self):
        content = "MDMA pills available. $50 for 10."
        result = sanitize_content(content)
        assert result.status == SanitizationStatus.CLEAN
        assert not result.illegal_flag
        assert len(result.detectors_fired) == 0

    def test_drug_content_not_dropped(self):
        content = "Cocaine for sale. Ship worldwide. Discrete packaging."
        result = sanitize_content(content)
        assert result.status != SanitizationStatus.DROPPED
        assert not result.illegal_flag

    def test_csam_keyword_dropped(self):
        content = "child porn available. DM for links."
        result = sanitize_content(content)
        assert result.status == SanitizationStatus.DROPPED
        assert result.illegal_flag
        assert len(result.detectors_fired) > 0

    def test_pedophilia_dropped(self):
        content = "pedo content available on request."
        result = sanitize_content(content)
        assert result.status == SanitizationStatus.DROPPED
        assert result.illegal_flag

    def test_yara_drug_indicators_flagged(self):
        content = """
        Ship worldwide. Discrete packaging. Stealth shipping.
        FE only. Finalized early. Escrow available.
        Bulk discount. Sample available.
        """
        result = sanitize_content(content)
        assert result.status in (SanitizationStatus.SANITIZED, SanitizationStatus.CLEAN)
        assert not result.illegal_flag
