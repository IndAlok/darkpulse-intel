from dataclasses import replace

from darkpulse.ingestion.hashing import sha256_hex
from darkpulse.ingestion.safety import RejectReason, SafetyPolicy


def evaluate(policy, record):
    content_bytes = record.raw_content.encode("utf-8")
    return policy.evaluate(
        record,
        source_sha256=sha256_hex(record.source_bytes),
        content_bytes=content_bytes,
        content_sha256=sha256_hex(content_bytes),
    )


def test_text_record_is_accepted(safety_policy, source_record) -> None:
    decision = evaluate(safety_policy, source_record)
    assert decision.accepted is True
    assert decision.reasons == ()
    assert "binary_persistence:false" in decision.checks


def test_binary_mime_type_is_rejected(safety_policy, source_record) -> None:
    record = replace(source_record, mime_type="image/jpeg")
    decision = evaluate(safety_policy, record)
    assert decision.accepted is False
    assert RejectReason.MIME_TYPE_NOT_ALLOWED in decision.reasons


def test_public_feed_mime_types_are_accepted(safety_policy, source_record) -> None:
    for mime_type in ("application/rss+xml", "application/xml", "text/xml", "application/atom+xml"):
        decision = evaluate(safety_policy, replace(source_record, mime_type=mime_type))
        assert decision.accepted is True, mime_type


def test_blocked_source_hash_is_rejected(source_record) -> None:
    source_hash = sha256_hex(source_record.source_bytes)
    policy = SafetyPolicy(
        policy_version="test",
        max_source_bytes=1000,
        max_content_bytes=1000,
        allowed_content_types=frozenset({source_record.content_type}),
        allowed_mime_types=frozenset({"application/json"}),
        blocked_source_prefixes=(),
        blocked_source_sha256=frozenset({source_hash}),
        blocked_content_sha256=frozenset(),
    )
    decision = evaluate(policy, source_record)
    assert decision.accepted is False
    assert RejectReason.SOURCE_HASH_BLOCKED in decision.reasons


def test_blocked_content_hash_is_rejected(source_record) -> None:
    content_hash = sha256_hex(source_record.raw_content.encode("utf-8"))
    policy = SafetyPolicy(
        policy_version="test",
        max_source_bytes=1000,
        max_content_bytes=1000,
        allowed_content_types=frozenset({source_record.content_type}),
        allowed_mime_types=frozenset({"application/json"}),
        blocked_source_prefixes=(),
        blocked_source_sha256=frozenset(),
        blocked_content_sha256=frozenset({content_hash}),
    )
    decision = evaluate(policy, source_record)
    assert decision.accepted is False
    assert RejectReason.CONTENT_HASH_BLOCKED in decision.reasons


def test_oversized_content_is_rejected(source_record) -> None:
    policy = SafetyPolicy(
        policy_version="test",
        max_source_bytes=10_000,
        max_content_bytes=1,
        allowed_content_types=frozenset({source_record.content_type}),
        allowed_mime_types=frozenset({"application/json"}),
        blocked_source_prefixes=(),
        blocked_source_sha256=frozenset(),
        blocked_content_sha256=frozenset(),
    )
    decision = evaluate(policy, source_record)
    assert RejectReason.CONTENT_TOO_LARGE in decision.reasons
