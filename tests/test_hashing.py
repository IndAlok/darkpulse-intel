from darkpulse.ingestion.hashing import (
    canonical_json_bytes,
    derive_dedup_key,
    sanitize_source_ref,
    sha256_hex,
)


def test_canonical_json_is_stable() -> None:
    left = canonical_json_bytes({"b": 2, "a": 1})
    right = canonical_json_bytes({"a": 1, "b": 2})
    assert left == right == b'{"a":1,"b":2}'


def test_source_ref_removes_credentials_fragment_and_secret_query() -> None:
    source_ref = "https://user:pass@example.test/path?token=secret&page=2&api_key=nope#fragment"
    assert sanitize_source_ref(source_ref) == "https://example.test/path?page=2"


def test_malformed_source_ref_is_fingerprinted_without_leaking_input() -> None:
    source_ref = "https://user:secret@example.test:not-a-port/path?token=also-secret"
    sanitized = sanitize_source_ref(source_ref)

    assert sanitized.startswith("invalid-ref://sha256/")
    assert "secret" not in sanitized


def test_dedup_key_is_stable_and_prefixed() -> None:
    content_hash = sha256_hex(b"content")
    first = derive_dedup_key(
        source_class="dnm_dataset",
        source_ref="dataset://example/1",
        content_sha256=content_hash,
    )
    second = derive_dedup_key(
        source_class="dnm_dataset",
        source_ref="dataset://example/1",
        content_sha256=content_hash,
    )
    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64
