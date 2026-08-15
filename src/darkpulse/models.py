from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
DEDUP_KEY_PATTERN = r"^sha256:[a-f0-9]{64}$"

JsonScalar = str | int | float | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceClass(StrEnum):
    DNM_DATASET = "dnm_dataset"
    TOR_MARKET = "tor_market"
    TOR_FORUM = "tor_forum"
    TELEGRAM = "telegram"
    SURFACE_MARKET = "surface_market"
    SOCIAL = "social"
    PASTE = "paste"
    I2P = "i2p"


class ContentType(StrEnum):
    HTML = "html"
    TEXT = "text"
    JSON = "json"
    MESSAGE = "message"


class SanitizationStatus(StrEnum):
    CLEAN = "clean"
    SANITIZED = "sanitized"
    DROPPED = "dropped"


class IntentLabel(StrEnum):
    SALE = "sale"
    SOLICITATION = "solicitation"
    DISCUSSION = "discussion"
    REVIEW = "review"
    UNRELATED = "unrelated"


class GeoBasis(StrEnum):
    EXPLICIT = "explicit"
    SLANG = "slang"
    SHIP_FROM = "ship_from"
    INFERENCE = "inference"


class ActorRelation(StrEnum):
    SAME_AS = "same_as"
    SELLS_TO = "sells_to"
    VENDS_ON = "vends_on"
    USES_WALLET = "uses_wallet"
    CO_POSTS = "co_posts"
    SHIPS_FROM = "ships_from"


class SeverityBand(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContactType(StrEnum):
    TELEGRAM = "telegram"
    WICKR = "wickr"
    SIGNAL = "signal"
    EMAIL = "email"
    PHONE_REDACTED = "phone_redacted"
    PGP = "pgp"


class LanguageInfo(BaseModel):
    detected: list[str] = Field(default_factory=list)
    code_mixed: bool = False
    romanized: bool = False


class Sanitization(BaseModel):
    status: SanitizationStatus
    detectors_fired: list[str] = Field(default_factory=list)
    illegal_flag: bool = False


class Intent(BaseModel):
    label: IntentLabel
    score: float = Field(ge=0, le=1)


class Product(BaseModel):
    canonical: str | None = None
    raw_term: str | None = None
    slang: bool = False
    quantity: str | None = None
    price: str | None = None


class SlangDecoded(BaseModel):
    term: str
    meaning: str | None = None
    lang: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    newly_discovered: bool = False


class GeoLocation(BaseModel):
    neighborhood: str | None = None
    city: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    basis: GeoBasis | None = None


class VendorEntity(BaseModel):
    alias: str | None = None
    platform: str | None = None


class CryptoWallet(BaseModel):
    chain: str | None = None
    address: str | None = None


class Contact(BaseModel):
    type: ContactType
    value_redacted: str | None = None


class Entities(BaseModel):
    vendors: list[VendorEntity] = Field(default_factory=list)
    buyers: list[dict[str, Any]] = Field(default_factory=list)
    crypto_wallets: list[CryptoWallet] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    pgp_fingerprints: list[str] = Field(default_factory=list)


class ActorLink(BaseModel):
    from_actor: str = Field(validation_alias="from", serialization_alias="from")
    to_actor: str = Field(validation_alias="to", serialization_alias="to")
    relation: ActorRelation
    confidence: float = Field(default=0.0, ge=0, le=1)

    model_config = ConfigDict(validate_by_name=True)


class Severity(BaseModel):
    score: float = Field(ge=0, le=100)
    band: SeverityBand
    factors: dict[str, Any] | None = None


def derive_intel_id(ingest_id: str, pipeline_version: str = "1.0.0") -> str:
    import hashlib

    digest = hashlib.sha256(f"{ingest_id}:{pipeline_version}".encode()).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


class TraffickingIntel(BaseModel):
    intel_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ingest_id: str
    trace_id: str | None = None
    source_class: str | None = None
    captured_at: datetime
    content_hash: str | None = None
    language: LanguageInfo | None = None
    sanitization: Sanitization
    translated_text: str | None = None
    intent: Intent
    products: list[Product] = Field(default_factory=list)
    slang_decoded: list[SlangDecoded] = Field(default_factory=list)
    geo: GeoLocation | None = None
    entities: Entities | None = None
    actor_links: list[ActorLink] = Field(default_factory=list)
    severity: Severity
    confidence: float = Field(ge=0, le=100)
    tags: list[str] = Field(default_factory=list)
    evidence_ref: str | None = None

    model_config = {"extra": "forbid"}


class CrawlMetadata(StrictModel):
    source_item_id: str | None = Field(default=None, max_length=512)
    status_code: int | None = Field(default=None, ge=100, le=599)
    latency_ms: int | None = Field(default=None, ge=0)
    retries: int = Field(default=0, ge=0)
    proxy_instance: str | None = Field(default=None, max_length=200)


class EvidenceMetadata(StrictModel):
    hash_algorithm: Literal["sha256"] = "sha256"
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    source_size_bytes: int = Field(ge=0)
    content_size_bytes: int = Field(ge=0)
    captured_at: datetime
    collector_id: str = Field(min_length=1, max_length=200)
    collector_version: str = Field(min_length=1, max_length=100)

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class SafetyMetadata(StrictModel):
    status: Literal["accepted"] = "accepted"
    policy_version: str = Field(min_length=1, max_length=100)
    checks: list[str] = Field(min_length=1)
    binary_content_stored: Literal[False] = False


class RawIngest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ingest_id: UUID
    trace_id: UUID
    dedup_key: str = Field(pattern=DEDUP_KEY_PATTERN)
    source_class: SourceClass
    source_ref: str = Field(min_length=1, max_length=2048)
    content_type: ContentType
    raw_content: str = Field(max_length=2_000_000)
    captured_at: datetime
    source_observed_at: datetime | None = None
    lang_hint: str | None = Field(default=None, max_length=32)
    geo_hints: list[str] = Field(default_factory=list, max_length=50)
    crawl_metadata: CrawlMetadata = Field(default_factory=CrawlMetadata)
    source_metadata: dict[str, JsonScalar] = Field(default_factory=dict)
    evidence: EvidenceMetadata
    safety: SafetyMetadata

    @field_validator("captured_at", "source_observed_at")
    @classmethod
    def require_timezones(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value


class Pagination(BaseModel):
    cursor: str | None = None
    limit: int = 50
    total: int = 0


class ErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: str | None = None


class ApiEnvelope(BaseModel):
    data: Any = None
    pagination: Pagination | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    errors: list[ErrorDetail] = Field(default_factory=list)


class IntelSummary(BaseModel):
    intel_id: str
    ingest_id: str
    source_class: str | None = None
    captured_at: datetime
    intent_label: str = ""
    intent_score: float = 0.0
    severity_score: float = 0.0
    severity_band: str = ""
    products: list[str] = Field(default_factory=list)
    neighborhood: str = ""
    vendor_aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    tags: list[str] = Field(default_factory=list)


class ActorSummary(BaseModel):
    actor_id: str
    alias: str
    platform: str = ""
    listing_count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    avg_severity: float = 0.0
    products: list[str] = Field(default_factory=list)
    neighborhoods: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    confidence: float = 0.0


class GraphData(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    truncated: bool = False
    limits: dict[str, int] = Field(default_factory=dict)


class TrendPoint(BaseModel):
    date: str
    count: int = 0
    products: dict[str, int] = Field(default_factory=dict)


class SourceRanking(BaseModel):
    source_class: str
    record_count: int = 0
    avg_severity: float = 0.0
    last_seen: datetime | None = None


class GeoHeatmapPoint(BaseModel):
    neighborhood: str
    count: int = 0
    avg_severity: float = 0.0
    top_products: list[str] = Field(default_factory=list)


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    terms: list[str] = Field(min_length=1, max_length=1000)
    notify: bool = True

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, terms: list[str]) -> list[str]:
        cleaned = [term.strip() for term in terms if term.strip()]
        if not cleaned:
            raise ValueError("terms must contain at least one non-empty term")
        if any(len(term) > 200 for term in cleaned):
            raise ValueError("each term must be at most 200 characters")
        return cleaned


class WatchlistUpdate(WatchlistCreate):
    enabled: bool = True


class WatchlistResponse(WatchlistUpdate):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    match_count: int = 0


class WatchlistListResponse(ApiEnvelope):
    data: list[WatchlistResponse] = Field(default_factory=list)


class SlangEntry(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    meaning: str = Field(min_length=1, max_length=200)
    lang: str = Field(default="en", min_length=1, max_length=32)
    confidence: float = Field(default=1.0, ge=0, le=1)
    newly_discovered: bool = False


class SlangUpdate(SlangEntry):
    review_status: Literal["pending", "approved", "rejected"] = "approved"


class SlangResponse(SlangUpdate):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    usage_count: int = 0


class SlangListResponse(ApiEnvelope):
    data: list[SlangResponse] = Field(default_factory=list)


class AlertRule(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    severity_min: int = Field(default=0, ge=0, le=100)
    products: list[str] = Field(default_factory=list, max_length=200)
    neighborhoods: list[str] = Field(default_factory=list, max_length=200)
    enabled: bool = True


class AlertConfig(BaseModel):
    rules: list[AlertRule] = Field(default_factory=list)


class AlertHistoryResponse(ApiEnvelope):
    data: list[dict[str, Any]] = Field(default_factory=list)
