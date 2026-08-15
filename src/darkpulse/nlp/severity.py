from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from darkpulse.models import IntentLabel, Severity, SeverityBand

logger = logging.getLogger(__name__)

_SOURCE_RELIABILITY: dict[str, float] = {
    "dnm_dataset": 0.90,
    "tor_market": 0.80,
    "tor_forum": 0.75,
    "telegram": 0.70,
    "surface_market": 0.50,
    "social": 0.45,
    "paste": 0.40,
    "i2p": 0.60,
}

_INTENT_SCORES: dict[IntentLabel, float] = {
    IntentLabel.SALE: 1.0,
    IntentLabel.SOLICITATION: 0.8,
    IntentLabel.DISCUSSION: 0.3,
    IntentLabel.REVIEW: 0.2,
    IntentLabel.UNRELATED: 0.0,
}

_PRODUCT_HARM: dict[str, float] = {
    "heroin": 1.0,
    "fentanyl": 1.0,
    "carfentanil": 1.0,
    "opium": 0.85,
    "oxycodone": 0.80,
    "hydrocodone": 0.75,
    "methamphetamine": 0.95,
    "cocaine": 0.85,
    "crack": 0.90,
    "amphetamine": 0.75,
    "mephedrone": 0.80,
    "mdpv": 0.80,
    "mdma": 0.70,
    "ecstasy": 0.70,
    "molly": 0.70,
    "lsd": 0.50,
    "psilocybin": 0.40,
    "dmt": 0.45,
    "mescaline": 0.40,
    "cannabis": 0.30,
    "weed": 0.30,
    "marijuana": 0.30,
    "hashish": 0.35,
    "hash": 0.35,
    "edible": 0.30,
    "ketamine": 0.60,
    "pcp": 0.70,
    "ghb": 0.65,
    "xanax": 0.55,
    "valium": 0.50,
    "benzodiazepine": 0.55,
    "spice": 0.80,
    "k2": 0.80,
    "inhalant": 0.50,
    "steroid": 0.30,
}

_DEFAULT_PRODUCT_HARM = 0.50

_BAND_THRESHOLDS: list[tuple[SeverityBand, float]] = [
    (SeverityBand.CRITICAL, 80.0),
    (SeverityBand.HIGH, 60.0),
    (SeverityBand.MEDIUM, 40.0),
    (SeverityBand.LOW, 20.0),
    (SeverityBand.INFO, 0.0),
]

_DEFAULT_WEIGHTS = {
    "intent": 0.25,
    "product_harm": 0.20,
    "source_reliability": 0.15,
    "localization": 0.15,
    "recency": 0.10,
    "exposure": 0.15,
}


def _get_source_reliability(source_class: str) -> float:
    return _SOURCE_RELIABILITY.get(source_class, 0.50)


def _get_intent_score(intent_label: IntentLabel) -> float:
    return _INTENT_SCORES.get(intent_label, 0.0)


def _get_product_harm(products: list[dict[str, Any]]) -> float:
    if not products:
        return 0.0

    max_harm = 0.0
    for product in products:
        canonical = product.get("canonical", "").lower()
        harm = _PRODUCT_HARM.get(canonical, 0.0)

        raw_term = product.get("raw_term", "").lower()
        if harm == 0.0 and raw_term:
            harm = _PRODUCT_HARM.get(raw_term, _DEFAULT_PRODUCT_HARM)

        max_harm = max(max_harm, harm)

    return max_harm


def _get_localization_score(
    geo_neighborhood: str,
    geo_city: str,
    geo_confidence: float,
) -> float:
    if geo_neighborhood:
        return min(1.0, 0.8 + geo_confidence * 0.2)
    if geo_city and geo_city.lower() == "surat":
        return min(0.8, 0.5 + geo_confidence * 0.3)
    if geo_city and geo_city.lower() in ("gujarat", "ahmedabad", "vadodara"):
        return 0.4
    if geo_city and geo_city.lower() in ("india", "mumbai", "delhi"):
        return 0.2
    return 0.1


def _get_recency_score(captured_at: datetime) -> float:
    now = datetime.now(UTC)

    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)

    age_hours = (now - captured_at).total_seconds() / 3600

    half_life = 72.0
    score = math.exp(-0.693 * age_hours / half_life)

    return max(0.0, min(1.0, score))


def _get_exposure_score(
    source_class: str,
    source_metadata: dict[str, Any] | None = None,
) -> float:
    base_scores = {
        "dnm_dataset": 0.70,
        "tor_market": 0.65,
        "tor_forum": 0.60,
        "telegram": 0.55,
        "surface_market": 0.40,
        "social": 0.35,
        "paste": 0.30,
        "i2p": 0.45,
    }

    base = base_scores.get(source_class, 0.50)

    if source_metadata:
        views = source_metadata.get("views", 0)
        if views > 10000:
            base = min(1.0, base + 0.2)
        elif views > 1000:
            base = min(1.0, base + 0.1)

        followers = source_metadata.get("followers", 0)
        if followers > 10000:
            base = min(1.0, base + 0.15)
        elif followers > 1000:
            base = min(1.0, base + 0.05)

    return base


def _determine_band(score: float) -> SeverityBand:
    for band, threshold in _BAND_THRESHOLDS:
        if score >= threshold:
            return band
    return SeverityBand.INFO


def calculate_severity(
    intent_label: IntentLabel = IntentLabel.UNRELATED,
    products: list[dict[str, Any]] | None = None,
    geo_neighborhood: str = "",
    geo_city: str = "",
    geo_confidence: float = 0.0,
    source_class: str = "",
    captured_at: datetime | None = None,
    source_metadata: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> Severity:
    if products is None:
        products = []
    if captured_at is None:
        captured_at = datetime.now(UTC)
    if weights is None:
        weights = _DEFAULT_WEIGHTS

    intent_score = _get_intent_score(intent_label)
    product_harm = _get_product_harm(products)
    source_reliability = _get_source_reliability(source_class)
    localization = _get_localization_score(geo_neighborhood, geo_city, geo_confidence)
    recency = _get_recency_score(captured_at)
    exposure = _get_exposure_score(source_class, source_metadata)

    weighted_score = (
        weights.get("intent", 0.25) * intent_score
        + weights.get("product_harm", 0.20) * product_harm
        + weights.get("source_reliability", 0.15) * source_reliability
        + weights.get("localization", 0.15) * localization
        + weights.get("recency", 0.10) * recency
        + weights.get("exposure", 0.15) * exposure
    )

    score = round(weighted_score * 100, 1)
    score = max(0.0, min(100.0, score))

    band = _determine_band(score)

    factors = {
        "intent": {
            "score": round(intent_score, 3),
            "weight": weights.get("intent", 0.25),
            "weighted": round(weights.get("intent", 0.25) * intent_score, 3),
            "label": intent_label.value,
        },
        "product_harm": {
            "score": round(product_harm, 3),
            "weight": weights.get("product_harm", 0.20),
            "weighted": round(weights.get("product_harm", 0.20) * product_harm, 3),
            "products": [p.get("canonical", "unknown") for p in products],
        },
        "source_reliability": {
            "score": round(source_reliability, 3),
            "weight": weights.get("source_reliability", 0.15),
            "weighted": round(weights.get("source_reliability", 0.15) * source_reliability, 3),
            "source": source_class,
        },
        "localization": {
            "score": round(localization, 3),
            "weight": weights.get("localization", 0.15),
            "weighted": round(weights.get("localization", 0.15) * localization, 3),
            "neighborhood": geo_neighborhood,
            "city": geo_city,
            "confidence": geo_confidence,
        },
        "recency": {
            "score": round(recency, 3),
            "weight": weights.get("recency", 0.10),
            "weighted": round(weights.get("recency", 0.10) * recency, 3),
            "captured_at": captured_at.isoformat(),
        },
        "exposure": {
            "score": round(exposure, 3),
            "weight": weights.get("exposure", 0.15),
            "weighted": round(weights.get("exposure", 0.15) * exposure, 3),
        },
    }

    return Severity(
        score=score,
        band=band,
        factors=factors,
    )
