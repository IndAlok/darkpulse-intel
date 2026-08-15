from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from jsonschema import Draft202012Validator, FormatChecker
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from darkpulse.api.excerpts import normalize_excerpt
from darkpulse.api.routes.alerts import broadcast_alert
from darkpulse.config import Settings
from darkpulse.models import RawIngest, TraffickingIntel
from darkpulse.nlp.pipeline import NLPPipeline
from darkpulse.nlp.runtime_dictionary import build_runtime_dictionary
from darkpulse.storage.mongodb import MongoManager
from darkpulse.storage.neo4j import Neo4jManager

logger = structlog.get_logger(__name__)


def _aware_utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class Contract2Validator:
    def __init__(self, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def validate(self, record: TraffickingIntel) -> None:
        self._validator.validate(record.model_dump(mode="json", by_alias=True, exclude_none=True))


class MongoProcessor:
    def __init__(self, settings: Settings, mongo: MongoManager, neo4j: Neo4jManager) -> None:
        self.settings = settings
        self.mongo = mongo
        self.neo4j = neo4j
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._fatal_error: str | None = None
        self._contract2_validator = Contract2Validator(settings.processor.contract2_path)
        self._nlp_pipeline: NLPPipeline | None = None
        self._slang_version: Any = None

    async def start(self) -> None:
        self._running = True
        logger.info("processor.starting")
        self._task = asyncio.create_task(self._run_loop(), name="raw-ingest-processor")

    async def stop(self) -> None:
        logger.info("processor.stopping")
        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        logger.info("processor.stopped")

    async def _run_loop(self) -> None:
        poll_interval = max(0.5, self.settings.processor.poll_interval_seconds)
        while self._running:
            try:
                doc = await self._claim_next()
                if doc is None:
                    await asyncio.sleep(poll_interval)
                    continue
                try:
                    await self._process_doc(doc)
                except Exception:
                    logger.exception("processor.record_failed", ingest_id=doc.get("ingest_id"))
                    await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._fatal_error = str(exc)
                logger.exception("processor.loop_error")
                await asyncio.sleep(poll_interval * 5)

    async def _claim_next(self) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(minutes=self.settings.processor.lease_minutes)
        max_attempts = self.settings.processor.max_attempts
        try:
            result: dict[str, Any] | None = await self.mongo.raw_ingest.find_one_and_update(
                {
                    "$or": [
                        {"processing": {"$exists": False}},
                        {"processing.status": "pending"},
                        {
                            "processing.status": "failed",
                            "processing.attempts": {"$lt": max_attempts},
                        },
                        {
                            "processing.status": "processing",
                            "processing.lease_expires_at": {"$lte": now},
                            "processing.attempts": {"$lt": max_attempts},
                        },
                    ]
                },
                {
                    "$set": {
                        "processing.status": "processing",
                        "processing.updated_at": now,
                        "processing.lease_expires_at": lease_expires_at,
                        "processing.last_error": None,
                    },
                    "$inc": {"processing.attempts": 1},
                },
                sort=[("_id", 1)],
                return_document=ReturnDocument.AFTER,
            )
            return result
        except Exception:
            logger.exception("processor.claim_failed")
            return None

    async def _process_doc(self, doc: dict[str, Any]) -> None:
        ingest_id = str(doc.get("ingest_id", ""))
        attempts = int((doc.get("processing") or {}).get("attempts", 1))
        max_attempts = self.settings.processor.max_attempts
        try:
            cleaned = {key: value for key, value in doc.items() if key not in ("_id", "processing")}
            cleaned["captured_at"] = _aware_utc(cleaned.get("captured_at"))
            cleaned["source_observed_at"] = _aware_utc(cleaned.get("source_observed_at"))
            evidence = cleaned.get("evidence")
            if isinstance(evidence, dict):
                evidence["captured_at"] = _aware_utc(evidence.get("captured_at"))
            record = RawIngest.model_validate(cleaned)
            await self._refresh_pipeline()
            if self._nlp_pipeline is None:
                raise RuntimeError("NLP pipeline unavailable")
            intel = await asyncio.to_thread(self._nlp_pipeline.process, record)
            if intel is not None:
                await self._process_intel(
                    intel.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
                await self._persist_slang_candidates()
                await self.mongo.intel.update_one(
                    {"intel_id": intel.intel_id},
                    {
                        "$set": {
                            "evidence_snapshot": {
                                "source_ref": str(record.source_ref),
                                "captured_at": record.captured_at.isoformat(),
                                "source_sha256": record.evidence.source_sha256,
                                "content_sha256": record.evidence.content_sha256,
                                "collector_id": record.evidence.collector_id,
                                "collector_version": record.evidence.collector_version,
                                "excerpt": normalize_excerpt(record.raw_content),
                            }
                        }
                    },
                )
            await self.mongo.raw_ingest.update_one(
                {"ingest_id": ingest_id},
                {
                    "$set": {
                        "processing.status": "dropped" if intel is None else "completed",
                        "processing.completed_at": datetime.now(UTC),
                        "processing.updated_at": datetime.now(UTC),
                        "processing.lease_expires_at": None,
                    }
                },
            )
        except Exception as exc:
            terminal = attempts >= max_attempts
            await self.mongo.raw_ingest.update_one(
                {"ingest_id": ingest_id},
                {
                    "$set": {
                        "processing.status": "exhausted" if terminal else "failed",
                        "processing.updated_at": datetime.now(UTC),
                        "processing.lease_expires_at": None,
                        "processing.last_error": type(exc).__name__,
                    }
                },
            )
            raise

    async def _refresh_pipeline(self) -> None:
        entries = await self.mongo.slang.find({"review_status": "approved"}).to_list(length=5000)
        version = tuple(
            sorted((str(entry.get("_id")), str(entry.get("updated_at", ""))) for entry in entries)
        )
        if self._nlp_pipeline is not None and version == self._slang_version:
            return
        dictionary = build_runtime_dictionary(self.settings.slang.seed_dictionary, entries)
        self._nlp_pipeline = NLPPipeline(
            slang_dictionary=dictionary,
            intent_model_path=self.settings.models.intent_model_path,
            fasttext_model_path=self.settings.models.fasttext_lid_path,
            severity_weights=self.settings.severity.to_dict(),
            auto_discovery_threshold=self.settings.slang.similarity_threshold,
            auto_discovery_min_occurrences=self.settings.slang.min_occurrences,
        )
        if not self.settings.slang.auto_discovery_enabled:
            self._nlp_pipeline._auto_discovery_unavailable = True
        self._slang_version = version
        logger.info("processor.slang_dictionary_refreshed", approved_entries=len(entries))

    async def _process_intel(self, payload: dict[str, Any]) -> None:
        record = TraffickingIntel.model_validate(payload)
        self._contract2_validator.validate(record)
        doc = record.model_dump(mode="json", by_alias=True, exclude_none=True)

        mongo_is_new = False
        try:
            await self.mongo.intel.insert_one(dict(doc))
            mongo_is_new = True
        except DuplicateKeyError:
            logger.debug("processor.intel.duplicate", intel_id=record.intel_id)

        await self.neo4j.upsert_intel_graph(doc)

        if mongo_is_new:
            await self._evaluate_alerts(record, doc)

        logger.info(
            "processor.intel.processed",
            intel_id=record.intel_id,
            ingest_id=record.ingest_id,
            trace_id=record.trace_id,
            severity_score=record.severity.score,
            is_new=mongo_is_new,
        )

    async def _evaluate_alerts(self, record: TraffickingIntel, doc: dict[str, Any]) -> None:
        config = await self.mongo.alerts_config.find_one({"_id": "default"})

        product_names = {p.canonical for p in record.products if p.canonical}
        neighborhood = (record.geo.neighborhood if record.geo else None) or ""
        score = record.severity.score

        for rule in (config or {}).get("rules", []):
            rule_name = rule.get("name", "Unknown Rule")
            severity_min = rule.get("severity_min", 0)
            rule_products = set(rule.get("products", []))
            rule_neighborhoods = set(rule.get("neighborhoods", []))
            enabled = rule.get("enabled", True)

            if not enabled:
                continue
            if score < severity_min:
                continue
            if rule_products and not (rule_products & product_names):
                continue
            if rule_neighborhoods and neighborhood not in rule_neighborhoods:
                continue

            alert_doc: dict[str, Any] = {
                "rule_name": rule_name,
                "intel_id": record.intel_id,
                "triggered_at": datetime.now(UTC),
                "severity_score": score,
                "context": f"Rule '{rule_name}' triggered (Score {score} >= {severity_min})",
                "acknowledged": False,
                "assignee": None,
                "resolved_at": None,
            }
            result = await self.mongo.alerts_history.insert_one(alert_doc)
            alert_doc["id"] = str(result.inserted_id)
            alert_doc.pop("_id", None)
            alert_doc["triggered_at"] = alert_doc["triggered_at"].isoformat()
            await broadcast_alert(alert_doc)
            logger.info("processor.alert.triggered", intel_id=record.intel_id, rule_name=rule_name)

        observed = " ".join(
            [
                str(doc.get("translated_text", "")),
                *[str(product.get("canonical", "")) for product in doc.get("products", [])],
                *[str(match.get("term", "")) for match in doc.get("slang_decoded", [])],
            ]
        ).casefold()
        watchlists = await self.mongo.watchlists.find({"enabled": True, "notify": True}).to_list(
            length=500
        )
        for watchlist in watchlists:
            matches = [
                term for term in watchlist.get("terms", []) if str(term).casefold() in observed
            ]
            if not matches:
                continue
            alert_doc = {
                "rule_name": f"Watchlist: {watchlist.get('name', 'Unnamed')}",
                "intel_id": record.intel_id,
                "triggered_at": datetime.now(UTC),
                "severity_score": score,
                "context": f"Matched monitored terms: {', '.join(matches[:10])}",
                "watchlist_id": str(watchlist.get("_id", "")),
                "acknowledged": False,
                "assignee": None,
                "resolved_at": None,
            }
            result = await self.mongo.alerts_history.insert_one(alert_doc)
            alert_doc["id"] = str(result.inserted_id)
            alert_doc.pop("_id", None)
            alert_doc["triggered_at"] = alert_doc["triggered_at"].isoformat()
            await broadcast_alert(alert_doc)

    async def _persist_slang_candidates(self) -> None:
        if self._nlp_pipeline is None or self._nlp_pipeline.auto_discovery is None:
            return
        now = datetime.now(UTC)
        for candidate in self._nlp_pipeline.auto_discovery.discover_candidates():
            meaning = ", ".join(candidate.similar_to[:3]) or "Pending analyst review"
            await self.mongo.slang.update_one(
                {"_id": f"pending:{candidate.term}"},
                {
                    "$setOnInsert": {
                        "term": candidate.term,
                        "meaning": meaning,
                        "lang": "und",
                        "confidence": min(1.0, max(0.0, candidate.similarity_score)),
                        "newly_discovered": True,
                        "review_status": "pending",
                        "created_at": now,
                    },
                    "$set": {"updated_at": now},
                },
                upsert=True,
            )

    @property
    def healthy(self) -> bool:
        return self._fatal_error is None and self._task is not None and not self._task.done()
