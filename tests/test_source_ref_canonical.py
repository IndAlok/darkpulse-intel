"""Canonical source_ref handling: NFC normalization and 2048-char truncation order."""

from darkpulse.ingestion.hashing import (
    derive_dedup_key,
    sanitize_source_ref,
    source_ref_fingerprint,
)

K = "a" * 64


def test_nfc_and_nfd_forms_get_one_key() -> None:
    nfc = "https://example.test/listing/café"
    nfd = "https://example.test/listing/cafe\u0301"
    assert nfc != nfd
    s_nfc = sanitize_source_ref(nfc)
    s_nfd = sanitize_source_ref(nfd)
    assert s_nfc == s_nfd, (s_nfc, s_nfd)
    assert derive_dedup_key(
        source_class="dnm_dataset", source_ref=s_nfc, content_sha256=K
    ) == derive_dedup_key(
        source_class="dnm_dataset", source_ref=s_nfd, content_sha256=K
    )


def test_refs_differing_only_past_2048_get_different_keys() -> None:
    base = "https://example.test/item/"
    a = base + "a" * 2200
    b = base + "b" * 2200
    s_a = sanitize_source_ref(a)
    s_b = sanitize_source_ref(b)
    assert len(s_a) == len(s_b) == 2048
    # same truncated prefix is NOT the dedup key; content fingerprint differs
    assert source_ref_fingerprint(s_a) != source_ref_fingerprint(s_b)
    assert derive_dedup_key(
        source_class="dnm_dataset", source_ref=s_a, content_sha256=K
    ) != derive_dedup_key(
        source_class="dnm_dataset", source_ref=s_b, content_sha256=K
    )


def test_plain_ref_truncated_to_2048() -> None:
    ref = "x" * 3000
    assert len(sanitize_source_ref(ref)) == 2048
