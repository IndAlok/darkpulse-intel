from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from darkpulse.models import (
    GeoLocation,
    Intent,
    IntentLabel,
    LanguageInfo,
    Product,
    SanitizationStatus,
    Severity,
    SeverityBand,
    SlangDecoded,
    TraffickingIntel,
    derive_intel_id,
)
from darkpulse.nlp.slang import SlangDictionary

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0.0"


class NLPPipeline:
    def __init__(
        self,
        slang_dictionary: SlangDictionary | None = None,
        intent_model_path: str | None = None,
        slang_seed_path: str | Path | None = None,
        fasttext_model_path: str | Path | None = None,
        severity_weights: dict[str, float] | None = None,
        known_actors: dict[str, Any] | None = None,
        auto_discovery_threshold: float = 0.7,
        auto_discovery_min_occurrences: int = 3,
    ) -> None:
        self._slang_dict = slang_dictionary or SlangDictionary()
        if slang_seed_path:
            self._slang_dict.load_seed(slang_seed_path)
        self._intent_classifier: Any | None = None
        self._fasttext_model_path = fasttext_model_path
        self._severity_weights = severity_weights
        self._known_actors = known_actors or {}
        self._auto_discovery: Any | None = None
        self._auto_discovery_unavailable = False
        self._auto_discovery_threshold = auto_discovery_threshold
        self._auto_discovery_min_occurrences = auto_discovery_min_occurrences
        if intent_model_path:
            self._load_intent_model(intent_model_path)
        self._metrics = {"processed": 0, "dropped": 0, "errors": 0}

    def _tokenize_terms(self, text: str) -> list[str]:
        import re

        return re.findall(r"[a-zA-Z\u0900-\u097F\u0A80-\u0AFF]{3,30}", text.lower())

    @property
    def auto_discovery(self) -> Any:
        return self._auto_discovery

    def _load_intent_model(self, model_path: str) -> None:
        try:
            from darkpulse.nlp.intent import IntentClassifier

            classifier = IntentClassifier()
            classifier.load_model(model_path)
            self._intent_classifier = classifier
        except Exception:
            logger.warning("Failed to load intent model from %s", model_path)
            self._intent_classifier = None

    def _get_intent_classifier(self) -> Any:
        if self._intent_classifier is None:
            from darkpulse.nlp.intent import IntentClassifier

            self._intent_classifier = IntentClassifier()
        return self._intent_classifier

    def process(self, record: Any) -> TraffickingIntel | None:
        import time

        start_time = time.time()
        ingest_id = str(record.ingest_id)
        trace_id = str(getattr(record, "trace_id", "")) or None
        source_class = (
            record.source_class.value
            if hasattr(record.source_class, "value")
            else str(record.source_class)
        )
        raw_content = record.raw_content
        captured_at = record.captured_at
        geo_hints = record.geo_hints or []
        source_metadata = getattr(record, "source_metadata", None) or {}

        try:
            from darkpulse.nlp.sanitizer import sanitize_content

            sanitization = sanitize_content(raw_content)

            if sanitization.status == SanitizationStatus.DROPPED:
                self._metrics["dropped"] += 1
                logger.info(
                    "Content dropped by sanitizer",
                    extra={"ingest_id": ingest_id, "detectors": sanitization.detectors_fired},
                )
                return None

            from darkpulse.nlp.ner.deterministic import extract_all_deterministic

            deterministic = extract_all_deterministic(raw_content)

            from darkpulse.nlp.language import (
                detect_language_info,
                load_fasttext_model,
                normalize_text,
            )
            from darkpulse.nlp.sanitizer import redact_sensitive_text

            load_fasttext_model(self._fasttext_model_path)
            normalized = normalize_text(raw_content)
            processed_text, pii_detectors = redact_sensitive_text(normalized.text)
            if pii_detectors:
                sanitization = sanitization.model_copy(
                    update={
                        "status": SanitizationStatus.SANITIZED,
                        "detectors_fired": [*sanitization.detectors_fired, *pii_detectors],
                    }
                )
            language_info = detect_language_info(processed_text)

            from darkpulse.nlp.ner import extract_all_entities

            entities, extracted_entities = extract_all_entities(
                processed_text,
                deterministic_results=deterministic,
            )

            slang_matches = self._slang_dict.decode_text(processed_text)
            slang_decoded = [SlangDecoded.model_validate(match) for match in slang_matches]

            from darkpulse.nlp.auto_discovery import SlangAutoDiscovery

            if self._auto_discovery is None and not self._auto_discovery_unavailable:
                try:
                    auto_discovery = SlangAutoDiscovery(
                        similarity_threshold=self._auto_discovery_threshold,
                        min_occurrences=self._auto_discovery_min_occurrences,
                        fasttext_model_path=(
                            str(self._fasttext_model_path) if self._fasttext_model_path else None
                        ),
                    )
                    auto_discovery.set_known_terms(set(self._slang_dict.terms))
                    self._auto_discovery = auto_discovery
                except ImportError:
                    self._auto_discovery_unavailable = True
                    logger.info("Auto-discovery disabled because optional dependencies are absent")
            if self._auto_discovery is not None:
                for word in self._tokenize_terms(processed_text):
                    self._auto_discovery.observe_term(word, context=processed_text[:200])

            intent_classifier = self._get_intent_classifier()
            intent = intent_classifier.classify(processed_text)

            from darkpulse.nlp.geo import match_geo

            geo = match_geo(
                processed_text,
                source_class=source_class,
                geo_hints=geo_hints,
            )

            from darkpulse.nlp.actors import detect_all_actor_links

            actor_links = detect_all_actor_links(
                entities,
                source_class=source_class,
                known_actors=self._known_actors,
            )

            products = self._build_products(extracted_entities, slang_decoded, deterministic)

            from darkpulse.nlp.severity import calculate_severity

            severity = calculate_severity(
                intent_label=intent.label,
                products=[p.model_dump(exclude_none=True) for p in products],
                geo_neighborhood=geo.neighborhood or "",
                geo_city=geo.city or "",
                geo_confidence=geo.confidence or 0.0,
                source_class=source_class,
                captured_at=captured_at,
                source_metadata=source_metadata,
                weights=self._severity_weights,
            )

            content_hash = hashlib.sha256(processed_text.encode()).hexdigest()

            intel = TraffickingIntel(
                intel_id=derive_intel_id(ingest_id, PIPELINE_VERSION),
                ingest_id=ingest_id,
                trace_id=trace_id,
                source_class=source_class,
                captured_at=captured_at,
                content_hash=content_hash,
                sanitization=sanitization,
                language=language_info,
                translated_text=processed_text[:5000],
                intent=intent,
                products=products,
                slang_decoded=slang_decoded if slang_decoded else [],
                geo=geo if geo.confidence and geo.confidence > 0 else None,
                entities=entities,
                actor_links=actor_links if actor_links else [],
                severity=severity,
                confidence=self._calculate_confidence(intent, geo, language_info),
            )

            self._metrics["processed"] += 1

            elapsed = time.time() - start_time
            logger.debug(
                "Processed record in %.2fs",
                elapsed,
                extra={
                    "ingest_id": ingest_id,
                    "intent": intent.label.value,
                    "severity_band": severity.band.value,
                    "products": [p.canonical for p in products if p.canonical],
                },
            )

            return intel

        except Exception:
            self._metrics["errors"] += 1
            logger.exception(
                "Error processing record",
                extra={"ingest_id": ingest_id},
            )
            raise

    def _build_products(
        self,
        extracted_entities: list[Any],
        slang_decoded: list[SlangDecoded],
        deterministic: dict[str, Any],
    ) -> list[Product]:
        products: list[Product] = []
        seen: set[str] = set()
        non_product_terms = {
            "area",
            "delivery",
            "home delivery",
            "city delivery",
            "fast delivery",
            "night order",
            "weekend order",
            "area number",
            "surat",
            "adajan area",
            "varachha area",
            "katargam area",
            "udhna area",
            "piplod area",
            "rander area",
            "athwa area",
            "vesu area",
            "dumas area",
            "pal area",
        }

        for entity in extracted_entities:
            if entity.label == "PRODUCT":
                canonical = entity.text.strip().lower()
                if canonical and canonical not in seen and canonical not in non_product_terms:
                    seen.add(canonical)
                    products.append(Product(canonical=canonical, raw_term=entity.text, slang=False))

        for slang in slang_decoded:
            term = (slang.term or "").lower()
            meaning = (slang.meaning or "").lower()
            if not meaning or meaning in non_product_terms:
                continue
            if meaning and meaning not in seen:
                seen.add(meaning)
                products.append(Product(canonical=meaning, raw_term=term, slang=True))

        prices = deterministic.get("prices", [])
        quantities = deterministic.get("quantities", [])
        if products and (prices or quantities):
            price_str = "; ".join(f"{p.amount} {p.currency}" for p in prices[:3])
            qty_str = "; ".join(f"{q.raw}" for q in quantities[:3])
            for product in products:
                if product.price is None and price_str:
                    product.price = price_str
                if product.quantity is None and qty_str:
                    product.quantity = qty_str

        return products

    def _make_intent(self, label: IntentLabel, score: float) -> Intent:
        from darkpulse.models import Intent

        return Intent(label=label, score=score)

    def _make_severity(self, score: float, band: str) -> Severity:
        return Severity(score=score, band=SeverityBand(band), factors={})

    def _calculate_confidence(
        self,
        intent: Intent,
        geo: GeoLocation,
        language_info: LanguageInfo | None,
    ) -> float:
        scores: list[float] = []
        if intent.score > 0:
            scores.append(intent.score)
        if geo.confidence and geo.confidence > 0:
            scores.append(geo.confidence)
        if language_info:
            scores.append(0.9 if not language_info.code_mixed else 0.7)
        if not scores:
            return 50.0
        avg = sum(scores) / len(scores)
        return float(round(min(100.0, max(0.0, avg * 100)), 1))

    @property
    def metrics(self) -> dict[str, int]:
        return self._metrics.copy()
