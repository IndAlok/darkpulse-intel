from __future__ import annotations

from darkpulse.models import Entities
from darkpulse.nlp.ner import (
    extract_all_entities,
    extract_product_mentions,
    extract_vendor_mentions,
)


class TestProductExtraction:
    def test_mdma_extraction(self):
        text = "MDMA pills available for sale"
        entities = extract_product_mentions(text)
        assert len(entities) >= 1
        assert any(e.label == "PRODUCT" for e in entities)

    def test_cocaine_extraction(self):
        text = "High quality cocaine. Pure powder."
        entities = extract_product_mentions(text)
        assert len(entities) >= 1

    def test_multiple_products(self):
        text = "MDMA, cocaine, and LSD available"
        entities = extract_product_mentions(text)
        assert len(entities) >= 2

    def test_slang_products(self):
        text = "Snow and molly available. Ice too."
        entities = extract_product_mentions(text)
        assert len(entities) >= 1


class TestVendorExtraction:
    def test_vendor_pattern(self):
        text = "Vendor: surat_supplier"
        entities = extract_vendor_mentions(text)
        assert len(entities) >= 1

    def test_from_pattern(self):
        text = "Bought from @surat_dealer"
        entities = extract_vendor_mentions(text)
        assert len(entities) >= 1


class TestFullNER:
    def test_returns_entities(self, sample_listing: str):
        entities, extracted = extract_all_entities(sample_listing)
        assert isinstance(entities, Entities)
        assert isinstance(extracted, list)

    def test_entities_with_deterministic(self, sample_with_crypto: str):
        from darkpulse.nlp.ner.deterministic import extract_crypto_wallets

        wallets = extract_crypto_wallets(sample_with_crypto)
        entities, extracted = extract_all_entities(
            sample_with_crypto,
            deterministic_results={"crypto_wallets": wallets},
        )
        assert len(entities.crypto_wallets) >= 1
