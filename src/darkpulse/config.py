from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8080, ge=1, le=65535)
    metrics_port: int = Field(default=9100, ge=0, le=65535)
    frontend_origin: str = "http://localhost:5173"


class ProcessorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    contract2_path: Path = Field(
        default=Path("contracts/contract2-intel.schema.json"),
        validation_alias="DARKPULSE_CONTRACT2_PATH",
    )
    poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=60.0,
        validation_alias=AliasChoices(
            "DARKPULSE_POLL_INTERVAL_SECONDS",
            "DARKPULSE_PROCESSOR_POLL_INTERVAL_SECONDS",
        ),
    )
    lease_minutes: int = Field(
        default=15,
        ge=1,
        le=120,
        validation_alias=AliasChoices(
            "DARKPULSE_LEASE_MINUTES",
            "DARKPULSE_PROCESSOR_LEASE_MINUTES",
        ),
    )
    max_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias=AliasChoices(
            "DARKPULSE_MAX_ATTEMPTS",
            "DARKPULSE_PROCESSOR_MAX_ATTEMPTS",
        ),
    )
    max_content_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1,
        le=100 * 1024 * 1024,
        validation_alias="DARKPULSE_PROCESSOR_MAX_CONTENT_BYTES",
    )


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    url: str = Field(default="redis://localhost:16379/0", validation_alias="DARKPULSE_REDIS_URL")


class MongoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    uri: str = Field(default="mongodb://localhost:27017", validation_alias="DARKPULSE_MONGODB_URI")
    database: str = Field(default="darkpulse", validation_alias="DARKPULSE_MONGODB_DATABASE")
    raw_ingest_collection: str = "raw_ingest"
    intel_collection: str = "intelligence"
    watchlists_collection: str = "watchlists"
    slang_collection: str = "slang"
    alerts_config_collection: str = "alerts_config"
    alerts_history_collection: str = "alerts_history"
    evidence_collection: str = "evidence_ledger"
    audit_collection: str = "audit_log"
    collection_runs_collection: str = "collection_runs"
    raw_retention_days: int = Field(
        default=30, ge=1, le=3650, validation_alias="DARKPULSE_RAW_RETENTION_DAYS"
    )
    skip_index_ensure: bool = Field(
        default=False, validation_alias="DARKPULSE_SKIP_INDEX_ENSURE"
    )


class Neo4jSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    uri: str = Field(default="bolt://localhost:7687", validation_alias="DARKPULSE_NEO4J_URI")
    user: str = Field(default="neo4j", validation_alias="DARKPULSE_NEO4J_USER")
    password: str = Field(default="darkpulse_dev", alias="NEO4J_PASSWORD")
    database: str = "neo4j"


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    fasttext_lid_path: str = Field(
        default="/models/lid.176.bin", validation_alias="DARKPULSE_FASTTEXT_LID_PATH"
    )
    intent_model_path: str = Field(
        default="/app/models/intent_classifier.joblib",
        validation_alias="DARKPULSE_INTENT_MODEL_PATH",
    )
    device: str = Field(default="cpu", validation_alias="DARKPULSE_MODEL_DEVICE")


class SlangSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    seed_dictionary: str = Field(
        default="/app/data/slang_dictionary/seed_dictionary.txt",
        validation_alias="DARKPULSE_SLANG_SEED_PATH",
    )


class GeoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    gazetteer: str = Field(
        default="builtin",
        validation_alias=AliasChoices("DARKPULSE_GAZETTEER", "DARKPULSE_GEO_GAZETTEER"),
    )
    city: str = Field(
        default="Surat",
        validation_alias=AliasChoices("DARKPULSE_CITY", "DARKPULSE_GEO_CITY"),
    )


class SeveritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    intent: float = Field(
        default=0.25,
        validation_alias=AliasChoices("DARKPULSE_INTENT", "DARKPULSE_SEVERITY_INTENT"),
    )
    product_harm: float = Field(
        default=0.20,
        validation_alias=AliasChoices(
            "DARKPULSE_PRODUCT_HARM", "DARKPULSE_SEVERITY_PRODUCT_HARM"
        ),
    )
    source_reliability: float = Field(
        default=0.15,
        validation_alias=AliasChoices(
            "DARKPULSE_SOURCE_RELIABILITY", "DARKPULSE_SEVERITY_SOURCE_RELIABILITY"
        ),
    )
    localization: float = Field(
        default=0.15,
        validation_alias=AliasChoices(
            "DARKPULSE_LOCALIZATION", "DARKPULSE_SEVERITY_LOCALIZATION"
        ),
    )
    recency: float = Field(
        default=0.10,
        validation_alias=AliasChoices("DARKPULSE_RECENCY", "DARKPULSE_SEVERITY_RECENCY"),
    )
    exposure: float = Field(
        default=0.15,
        validation_alias=AliasChoices("DARKPULSE_EXPOSURE", "DARKPULSE_SEVERITY_EXPOSURE"),
    )

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> Self:
        total = (
            self.intent
            + self.product_harm
            + self.source_reliability
            + self.localization
            + self.recency
            + self.exposure
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError("severity weights must sum to 1.0")
        return self

    def to_dict(self) -> dict[str, float]:
        return {
            "intent": self.intent,
            "product_harm": self.product_harm,
            "source_reliability": self.source_reliability,
            "localization": self.localization,
            "recency": self.recency,
            "exposure": self.exposure,
        }


class CollectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    collector_id: str = "darkpulse-collector"
    collector_version: str = "1.0.0"
    dedup_ttl_seconds: int = Field(default=7_776_000, gt=0)
    contract_path: Path = Field(
        default=Path("contracts/contract1-raw-ingest.schema.json"),
        validation_alias="DARKPULSE_CONTRACT_PATH",
    )
    safety_policy_path: Path = Field(
        default=Path("safety/policy/prepublish-v1.json"),
        validation_alias="DARKPULSE_SAFETY_POLICY_PATH",
    )
    sources_path: Path = Path("config/sources.json")
    onion_review_policy_path: Path = Path("config/onion-review.json")
    tor_proxy_url: str = "socks5://localhost:9050"
    telegram_api_id: int | None = Field(default=None, gt=0)

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def blank_telegram_api_id(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value
    telegram_api_hash: SecretStr | None = None
    telegram_runtime_root: Path = Path("runtime/telegram")
    telegram_session_path: Path = Path("runtime/telegram/darkpulse")
    telegram_max_messages: int = Field(default=100, ge=1, le=1000)


class EvidenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    rfc3161_enabled: bool = False
    rfc3161_tsa_url: str = ""


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    enabled: bool = Field(default=False, validation_alias="DARKPULSE_AUTH_ENABLED")
    local_open_mode: bool = Field(default=False, validation_alias="DARKPULSE_LOCAL_OPEN_MODE")
    tokens_json: SecretStr | None = Field(
        default=None, validation_alias="DARKPULSE_AUTH_TOKENS_JSON"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    service: ServiceSettings = Field(default_factory=ServiceSettings)
    processor: ProcessorSettings = Field(default_factory=ProcessorSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    mongo: MongoSettings = Field(default_factory=MongoSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    slang: SlangSettings = Field(default_factory=SlangSettings)
    geo: GeoSettings = Field(default_factory=GeoSettings)
    severity: SeveritySettings = Field(default_factory=SeveritySettings)
    collection: CollectionSettings = Field(default_factory=CollectionSettings)
    evidence: EvidenceSettings = Field(default_factory=EvidenceSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)


_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def allowed_origins(settings: Settings) -> set[str]:
    if settings.service.environment.lower() == "development":
        return {"http://localhost:5173", "http://localhost:3000", settings.service.frontend_origin}
    return {settings.service.frontend_origin}


def _require_datastore_tls(uri: str, name: str) -> None:
    parsed = urlsplit(uri)
    if parsed.scheme in {"mongodb+srv", "rediss"}:
        return
    query = parsed.query.lower()
    if "tls=true" in query or "ssl=true" in query:
        return
    hosts = {part.rsplit("@", 1)[-1].split(":")[0] for part in parsed.netloc.split(",")}
    if hosts and hosts <= _LOOPBACK:
        return
    raise RuntimeError(f"Production {name} URI must use TLS")


def enforce_boot(settings: Settings) -> None:
    environment = settings.service.environment.strip().lower()
    if environment not in {"development", "staging", "production"}:
        raise RuntimeError(
            "DARKPULSE_ENVIRONMENT must be development, staging, or production"
        )
    if settings.auth.enabled:
        secret = settings.auth.tokens_json
        if secret is None or not secret.get_secret_value().strip():
            raise RuntimeError(
                "DARKPULSE_AUTH_ENABLED requires DARKPULSE_AUTH_TOKENS_JSON"
            )
        try:
            tokens = json.loads(secret.get_secret_value())
        except json.JSONDecodeError as exc:
            raise RuntimeError("DARKPULSE_AUTH_TOKENS_JSON is not valid JSON") from exc
        if not isinstance(tokens, dict) or not tokens:
            raise RuntimeError("DARKPULSE_AUTH_TOKENS_JSON must map tokens to principals")
        for token in tokens:
            if len(token) < 32 or "CHANGE_ME" in token:
                raise RuntimeError("Each auth token must be at least 32 random characters")
    elif not settings.auth.local_open_mode:
        raise RuntimeError(
            "DARKPULSE_AUTH_ENABLED is required unless DARKPULSE_LOCAL_OPEN_MODE is set"
        )
    elif settings.service.api_host not in _LOOPBACK:
        raise RuntimeError("DARKPULSE_LOCAL_OPEN_MODE requires a loopback bind")
    production = environment == "production"
    if production and settings.auth.local_open_mode:
        raise RuntimeError("DARKPULSE_LOCAL_OPEN_MODE is not allowed in production")
    if not settings.auth.local_open_mode and (
        len(settings.neo4j.password) < 12
        or settings.neo4j.password in {"", "darkpulse_dev", "neo4j"}
    ):
        raise RuntimeError(
            "A non-default Neo4j password (NEO4J_PASSWORD) of at least 12 characters is required."
        )
    if settings.evidence.rfc3161_enabled:
        raise RuntimeError("RFC3161 is enabled but the pinned verifier is not configured")
    if production:
        _require_datastore_tls(settings.mongo.uri, "MongoDB")
        _require_datastore_tls(settings.redis.url, "Redis")
        if not settings.service.frontend_origin.startswith("https://"):
            raise RuntimeError("Production requires an HTTPS DARKPULSE_FRONTEND_ORIGIN.")
        if (
            settings.service.metrics_port
            and settings.service.api_host not in _LOOPBACK
            and os.getenv("DARKPULSE_METRICS_PUBLIC", "").lower() != "true"
        ):
            raise RuntimeError(
                "Production metrics port on a non-loopback host requires "
                "DARKPULSE_METRICS_PUBLIC=true"
            )


_REPO_ROOT = Path(__file__).resolve().parents[2]

_RELATIVE_PATHS = (
    ("processor", "contract2_path"),
    ("collection", "safety_policy_path"),
    ("collection", "contract_path"),
    ("collection", "sources_path"),
    ("collection", "onion_review_policy_path"),
)


def _resolve_repo_paths(settings: Settings) -> None:
    for section_name, field_name in _RELATIVE_PATHS:
        section = getattr(settings, section_name)
        path = getattr(section, field_name)
        if path is not None and not path.is_absolute():
            setattr(section, field_name, _REPO_ROOT / path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    _resolve_repo_paths(settings)
    return settings
