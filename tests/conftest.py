from __future__ import annotations

import os

os.environ.setdefault("DARKPULSE_LOCAL_OPEN_MODE", "true")
os.environ.setdefault("DARKPULSE_API_HOST", "127.0.0.1")
os.environ.setdefault("DARKPULSE_METRICS_PORT", "0")

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from darkpulse.api import security as _security
from darkpulse.config import Settings
from darkpulse.ingestion.hashing import canonical_json_bytes
from darkpulse.ingestion.records import SourceRecord
from darkpulse.ingestion.safety import SafetyPolicy
from darkpulse.models import ContentType, CrawlMetadata, SourceClass
from darkpulse.nlp.slang import SlangDictionary, SlangEntry

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "contracts/contract1-raw-ingest.schema.json"
SAFETY_POLICY_PATH = REPO_ROOT / "safety/policy/prepublish-v1.json"

_security._redis_disabled = True

_DATASTORE_PATCHES = (
    "darkpulse.broker.processor.MongoProcessor.start",
    "darkpulse.broker.processor.MongoProcessor.stop",
    "darkpulse.storage.mongodb.MongoManager.connect",
    "darkpulse.storage.mongodb.MongoManager.close",
    "darkpulse.storage.mongodb.MongoManager.health",
    "darkpulse.storage.mongodb.MongoManager.ensure_application_defaults",
    "darkpulse.storage.neo4j.Neo4jManager.connect",
    "darkpulse.storage.neo4j.Neo4jManager.close",
    "darkpulse.storage.neo4j.Neo4jManager.health",
)


@pytest.fixture(autouse=True)
def _stub_app_datastores(request: pytest.FixtureRequest):
    if request.node.get_closest_marker("live_datastores"):
        yield
        return
    started = [patch(target, new_callable=AsyncMock) for target in _DATASTORE_PATCHES]
    for item in started:
        item.start()
    yield
    for item in reversed(started):
        item.stop()


@pytest.fixture(autouse=True)
def _isolated_rate_limits() -> None:
    from darkpulse.api import rate_limit

    rate_limit.reset_rate_limits()
    rate_limit._redis_disabled = True
    yield
    rate_limit.reset_rate_limits()


TEST_TOKEN = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def auth_settings() -> Settings:
    """Settings with a configured token, for tests that override get_settings."""
    from pydantic import SecretStr

    settings = Settings()
    settings.auth.enabled = True
    settings.auth.local_open_mode = False
    settings.auth.tokens_json = SecretStr(
        f'{{"{TEST_TOKEN}": {{"subject": "analyst-001", "role": "analyst"}}}}'
    )
    return settings


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer headers from a real session, for TestClient calls."""
    from darkpulse.api.security import Principal, mint_session

    principal = Principal(subject="analyst-001", role="analyst")
    session = mint_session(principal, TEST_TOKEN)
    return {"Authorization": f"Bearer {session}"}


@pytest.fixture
def safety_policy() -> SafetyPolicy:
    return SafetyPolicy.from_path(SAFETY_POLICY_PATH)


@pytest.fixture
def source_record() -> SourceRecord:
    row = {
        "description": "Fixture text",
        "id": "row-1",
        "title": "Fixture title",
    }
    raw_content = canonical_json_bytes(row).decode("utf-8")
    return SourceRecord(
        source_class=SourceClass.DNM_DATASET,
        source_ref="dataset://fixture/row-1",
        content_type=ContentType.JSON,
        mime_type="application/json",
        raw_content=raw_content,
        source_bytes=raw_content.encode("utf-8"),
        captured_at=datetime.now(UTC),
        crawl_metadata=CrawlMetadata(source_item_id="row-1"),
        source_metadata={"fixture": True},
    )


@pytest.fixture
def slang_dict() -> SlangDictionary:
    d = SlangDictionary()
    entries = [
        SlangEntry(term="snow", canonical="cocaine", language="en", source="test"),
        SlangEntry(term="ice", canonical="methamphetamine", language="en", source="test"),
        SlangEntry(term="molly", canonical="MDMA", language="en", source="test"),
        SlangEntry(term="maal", canonical="drugs", language="hi", source="test"),
        SlangEntry(term="goli", canonical="pill", language="hi", source="test"),
        SlangEntry(term="chitta", canonical="heroin", language="gu", source="test"),
        SlangEntry(term="🍃", canonical="cannabis", language="emoji", source="test"),
        SlangEntry(term="❄️", canonical="cocaine", language="emoji", source="test"),
        SlangEntry(term="💊", canonical="MDMA", language="emoji", source="test"),
    ]
    for entry in entries:
        d.add_entry(entry)
    return d


@pytest.fixture
def sample_listing() -> str:
    return """
    MDMA Pills Available - High Quality

    Price: $50 for 10 pills
    Shipping: Worldwide, discrete packaging
    Vendor: @surat_supplier
    Location: Adajan, Surat

    FE only for trusted buyers. Bulk discounts available.
    BTC accepted: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa

    Contact: t.me/surat_supplier
    """


@pytest.fixture
def sample_review() -> str:
    return """
    Great vendor! Fast shipping and quality product.
    The MDMA was pure and strong. 10/10 would recommend.
    Discrete packaging, arrived in 3 days.
    Will definitely order again from this seller.
    """


@pytest.fixture
def sample_discussion() -> str:
    return """
    What's a safe dose of MDMA for first time?
    I've heard 100mg is a good starting point.
    Should I test it with a reagent kit first?
    Also, how long does the high last?
    """


@pytest.fixture
def sample_solicitation() -> str:
    return """
    Looking for MDMA in Surat area.
    Need reliable vendor that ships to Adajan.
    Anyone have a good connect? DM me.
    Prefer quality over price.
    """


@pytest.fixture
def sample_with_crypto() -> str:
    return """
    Send payment to:
    BTC: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
    ETH: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18
    XMR: 44AFFq5kSiGBoZ4NMDwYtN18NhmFpLjCVRt6LGzKBq7bA6zFjJhTfJbJfJbJfJbJfJbJfJbJfJbJfJb
    """


@pytest.fixture
def sample_with_contacts() -> str:
    return """
    Contact us:
    Telegram: @surat_dealer
    Wickr: suratplug
    Email: dealer@example.com
    Signal: +919876543210
    """
