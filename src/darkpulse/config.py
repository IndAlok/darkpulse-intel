from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8080, ge=1, le=65535)
    frontend_origin: str = "http://localhost:5173"


class ProcessorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    contract2_path: Path = Field(
        default=Path("contracts/contract2-intel.schema.json"),
        validation_alias="DARKPULSE_CONTRACT2_PATH",
    )
    poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=60.0)
    lease_minutes: int = Field(default=15, ge=1, le=120)
    max_attempts: int = Field(default=5, ge=1, le=20)


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

    muril_name: str = Field(
        default="google/muril-base-cased", validation_alias="DARKPULSE_MURIL_MODEL"
    )
    indicner_name: str = Field(
        default="ai4bharat/IndicNER", validation_alias="DARKPULSE_INDICNER_MODEL"
    )
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
    auto_discovery_enabled: bool = True
    similarity_threshold: float = 0.7
    min_occurrences: int = 3


class GeoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    gazetteer: str = "builtin"
    city: str = "Surat"


class SeveritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARKPULSE_", env_file=".env", extra="ignore")

    intent: float = 0.25
    product_harm: float = 0.20
    source_reliability: float = 0.15
    localization: float = 0.15
    recency: float = 0.10
    exposure: float = 0.15

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
