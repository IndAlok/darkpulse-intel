from __future__ import annotations

from datetime import UTC, datetime

from darkpulse.models import IntentLabel, SeverityBand
from darkpulse.nlp.severity import calculate_severity


class TestSeverityScoring:
    def test_sale_with_surat_match(self):
        severity = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "MDMA", "raw_term": "molly"}],
            geo_neighborhood="adajan",
            geo_city="Surat",
            geo_confidence=0.9,
            source_class="telegram",
            captured_at=datetime.now(UTC),
        )
        assert severity.score >= 50
        assert severity.band in (SeverityBand.HIGH, SeverityBand.MEDIUM, SeverityBand.CRITICAL)

    def test_unrelated_low_score(self):
        severity = calculate_severity(
            intent_label=IntentLabel.UNRELATED,
            products=[],
            geo_neighborhood="",
            geo_city="",
            geo_confidence=0.0,
            source_class="surface_market",
            captured_at=datetime.now(UTC),
        )
        assert severity.score <= 30
        assert severity.band in (SeverityBand.INFO, SeverityBand.LOW)

    def test_heroin_higher_than_cannabis(self):
        heroin = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "heroin"}],
            source_class="tor_market",
            captured_at=datetime.now(UTC),
        )
        cannabis = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "cannabis"}],
            source_class="tor_market",
            captured_at=datetime.now(UTC),
        )
        assert heroin.score > cannabis.score

    def test_factors_explainable(self):
        severity = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "MDMA"}],
            source_class="telegram",
            captured_at=datetime.now(UTC),
        )
        assert "intent" in severity.factors
        assert "product_harm" in severity.factors
        assert "source_reliability" in severity.factors
        assert "localization" in severity.factors
        assert "recency" in severity.factors
        assert "exposure" in severity.factors

    def test_band_assignment(self):
        severity = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "fentanyl"}],
            geo_neighborhood="adajan",
            geo_city="Surat",
            geo_confidence=0.95,
            source_class="tor_market",
            captured_at=datetime.now(UTC),
        )
        assert severity.band in (SeverityBand.CRITICAL, SeverityBand.HIGH)

    def test_recency_decay(self):
        recent = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "MDMA"}],
            source_class="telegram",
            captured_at=datetime.now(UTC),
        )
        old = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "MDMA"}],
            source_class="telegram",
            captured_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert recent.score > old.score

    def test_custom_weights(self):
        default = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "MDMA"}],
            source_class="telegram",
            captured_at=datetime.now(UTC),
        )
        intent_heavy = calculate_severity(
            intent_label=IntentLabel.SALE,
            products=[{"canonical": "MDMA"}],
            source_class="telegram",
            captured_at=datetime.now(UTC),
            weights={
                "intent": 0.5,
                "product_harm": 0.1,
                "source_reliability": 0.1,
                "localization": 0.1,
                "recency": 0.1,
                "exposure": 0.1,
            },
        )
        assert default.score != intent_heavy.score
