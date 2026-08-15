from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from darkpulse.ingestion.hashing import canonical_json_bytes
from darkpulse.ingestion.records import SourceRecord
from darkpulse.ingestion.safety import SafetyPolicy
from darkpulse.models import ContentType, CrawlMetadata, SourceClass
from darkpulse.nlp.slang import SlangDictionary, SlangEntry

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "contracts/contract1-raw-ingest.schema.json"
SAFETY_POLICY_PATH = REPO_ROOT / "safety/policy/prepublish-v1.json"

patch("darkpulse.broker.processor.MongoProcessor.start", new_callable=AsyncMock).start()
patch("darkpulse.broker.processor.MongoProcessor.stop", new_callable=AsyncMock).start()
patch("darkpulse.storage.mongodb.MongoManager.connect", new_callable=AsyncMock).start()
patch("darkpulse.storage.mongodb.MongoManager.close", new_callable=AsyncMock).start()
patch("darkpulse.storage.mongodb.MongoManager.health", new_callable=AsyncMock).start()
patch(
    "darkpulse.storage.mongodb.MongoManager.ensure_application_defaults", new_callable=AsyncMock
).start()
patch("darkpulse.storage.neo4j.Neo4jManager.connect", new_callable=AsyncMock).start()
patch("darkpulse.storage.neo4j.Neo4jManager.close", new_callable=AsyncMock).start()
patch("darkpulse.storage.neo4j.Neo4jManager.health", new_callable=AsyncMock).start()


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
