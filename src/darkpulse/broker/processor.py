from __future__ import annotations

import asyncio
import json
import re
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
from darkpulse.ingestion.dedup import DedupStore
from darkpulse.models import RawIngest, TraffickingIntel
from darkpulse.nlp.pipeline import NLPPipeline
from darkpulse.nlp.runtime_dictionary import build_runtime_dictionary
from darkpulse.storage.mongodb import MongoManager
from darkpulse.storage.neo4j import Neo4jManager

logger = structlog.get_logger(__name__)
_NLP_TIMEOUT_SECONDS = 300


def _aware_utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _term_in_text(term: str, observed: str) -> bool:
    needle = term.casefold().strip()
    if len(needle) < 2:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", observed) is not None


class Contract2Validator:
    def __init__(self, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def validate(self, record: TraffickingIntel) -> None:
        self._validator.validate(record.model_dump(mode="json", by_alias=True, exclude_none=True))


class MongoProcessor:
    def __init__(
        self,
        settings: Settings,
        mongo: MongoManager,
        neo4j: Neo4jManager,
        dedup: DedupStore | None = None,
    ) -> None:
        self.settings = settings
        self.mongo = mongo
        self.neo4j = neo4j
        self.dedup = dedup
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
        await self._release_open_leases()
        logger.info("processor.stopped")

    async def _run_loop(self) -> None:
        poll_interval = max(0.5, self.settings.processor.poll_interval_seconds)
        while self._running:
            try:
                await self._exhaust_stale_leases()
                if not await self._graph_ready():
                    await asyncio.sleep(poll_interval * 5)
                    continue
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

    async def _graph_ready(self) -> bool:
        if (await self.neo4j.health()).get("status") == "healthy":
            return True
        try:
            await self.neo4j.connect()
        except Exception:
            self._fatal_error = "graph_unavailable"
            logger.warning("processor.waiting_for_graph")
            return False
        self._fatal_error = None
        return True

    async def _exhaust_stale_leases(self) -> None:
        now = datetime.now(UTC)
        await self.mongo.raw_ingest.update_many(
            {
                "processing.status": "processing",
                "processing.lease_expires_at": {"$lte": now},
                "processing.attempts": {"$gte": self.settings.processor.max_attempts},
            },
            {
                "$set": {
                    "processing.status": "exhausted",
                    "processing.updated_at": now,
                    "processing.lease_expires_at": None,
                }
            },
        )

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
                        {
                            "processing.status": "waiting_dependency",
                            "processing.lease_expires_at": {"$lte": now},
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
        except Exception:
            self._fatal_error = "claim_failed"
            logger.exception("processor.claim_failed")
            return None
        self._fatal_error = None
        return result

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
            raw_content = (record.raw_content or "").strip()
            if not raw_content:
                await self._finish_raw(ingest_id, dropped=True)
                logger.info("processor.empty_content_dropped", ingest_id=ingest_id)
                return
            max_bytes = self.settings.processor.max_content_bytes
            if max_bytes and len(raw_content) > max_bytes:
                await self.mongo.raw_ingest.update_one(
                    {"ingest_id": ingest_id},
                    {
                        "$set": {
                            "processing.status": "failed",
                            "processing.updated_at": datetime.now(UTC),
                            "processing.lease_expires_at": None,
                            "processing.last_error": "content_too_large",
                        }
                    },
                )
                raise ValueError("raw_content exceeds processor cap")
            if await self._resume_saved(doc, record, ingest_id):
                return
            await self._refresh_pipeline()
            if self._nlp_pipeline is None:
                raise RuntimeError("NLP pipeline unavailable")
            known_actors = await self._known_actors(ingest_id)
            intel = await asyncio.wait_for(
                asyncio.to_thread(self._nlp_pipeline.process, record, known_actors),
                timeout=_NLP_TIMEOUT_SECONDS,
            )
            if intel is not None:
                saved = await self._process_intel(
                    intel.model_dump(mode="json", by_alias=True, exclude_none=True)
                )
                if not saved:
                    return
                await self._write_snapshot(intel.intel_id, record)
            await self._finish_raw(ingest_id, dropped=intel is None)
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

    async def _resume_saved(self, doc: dict[str, Any], record: RawIngest, ingest_id: str) -> bool:
        processing = doc.get("processing") or {}
        if processing.get("phase") != "intel_saved":
            return False
        intel_id = str(processing.get("intel_id") or "")
        if not intel_id:
            return False
        existing = await self.mongo.intel.find_one({"intel_id": intel_id})
        if not isinstance(existing, dict):
            return False
        payload = {
            key: value for key, value in existing.items() if key in TraffickingIntel.model_fields
        }
        if not await self._process_intel(payload):
            return True
        await self._write_snapshot(intel_id, record)
        await self._finish_raw(ingest_id, dropped=False)
        return True

    async def _write_snapshot(self, intel_id: str, record: RawIngest) -> None:
        await self.mongo.intel.update_one(
            {"intel_id": intel_id},
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

    async def _finish_raw(self, ingest_id: str, *, dropped: bool) -> None:
        await self.mongo.raw_ingest.update_one(
            {"ingest_id": ingest_id},
            {
                "$set": {
                    "processing.status": "dropped" if dropped else "completed",
                    "processing.completed_at": datetime.now(UTC),
                    "processing.updated_at": datetime.now(UTC),
                    "processing.lease_expires_at": None,
                    "processing.phase": "completed",
                }
            },
        )

    async def _known_actors(self, exclude_ingest: str) -> dict[str, Any]:
        docs = await (
            self.mongo.intel.find(
                {"ingest_id": {"$ne": exclude_ingest}},
                {"entities": 1, "intel_id": 1},
            )
            .sort("captured_at", -1)
            .to_list(length=500)
        )
        aliases: dict[str, list[str]] = {}
        fingerprints: dict[str, list[str]] = {}
        wallets: dict[str, list[str]] = {}
        for doc in docs:
            entities = doc.get("entities") or {}
            vendor_aliases = [
                str(vendor["alias"])
                for vendor in entities.get("vendors") or []
                if isinstance(vendor, dict) and vendor.get("alias")
            ]
            actor = vendor_aliases[0] if vendor_aliases else f"intel:{doc.get('intel_id')}"
            for alias in vendor_aliases:
                aliases.setdefault(alias, []).append(alias)
            fingerprints.setdefault(actor, []).extend(
                fp for fp in entities.get("pgp_fingerprints") or [] if isinstance(fp, str)
            )
            wallets.setdefault(actor, []).extend(
                str(wallet["address"])
                for wallet in entities.get("crypto_wallets") or []
                if isinstance(wallet, dict) and wallet.get("address")
            )
        return {"aliases": aliases, "pgp_fingerprints": fingerprints, "crypto_wallets": wallets}

    async def _refresh_pipeline(self) -> None:
        try:
            entries = await self.mongo.slang.find(
                {"review_status": {"$in": ["approved", "rejected"]}}
            ).to_list(length=None)
        except Exception:
            # keep the last good dictionary rather than silently publishing
            # with an empty one
            logger.exception("processor.slang_read_failed")
            if self._nlp_pipeline is not None:
                return
            raise
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
            auto_discovery=False,
        )
        self._slang_version = version
        logger.info("processor.slang_dictionary_refreshed", approved_entries=len(entries))

    async def _process_intel(self, payload: dict[str, Any]) -> bool:
        record = TraffickingIntel.model_validate(payload)
        self._contract2_validator.validate(record)
        doc = record.model_dump(mode="json", by_alias=True, exclude_none=True)

        mongo_is_new = False
        try:
            await self.mongo.intel.insert_one(dict(doc))
            mongo_is_new = True
        except DuplicateKeyError:
            # intel already exists (replay after a raw-TTL edge or a partial
            # prior run): clear the dedup key so the next cycle republishes
            raw = await self.mongo.raw_ingest.find_one({"ingest_id": str(record.ingest_id)})
            if raw and raw.get("dedup_key") and self.dedup is not None:
                await self.dedup.forget(raw["dedup_key"])
            logger.debug("processor.intel.duplicate", intel_id=record.intel_id)

        try:
            await self.neo4j.upsert_intel_graph(doc)
        except Exception as exc:
            await self._mark_waiting(record.ingest_id, record.intel_id, exc)
            return False
        await self._evaluate_alerts(record, doc)

        logger.info(
            "processor.intel.processed",
            intel_id=record.intel_id,
            ingest_id=record.ingest_id,
            trace_id=record.trace_id,
            severity_score=record.severity.score,
            is_new=mongo_is_new,
        )
        return True

    async def _mark_waiting(self, ingest_id: str, intel_id: str, exc: Exception) -> None:
        now = datetime.now(UTC)
        current = await self.mongo.raw_ingest.find_one(
            {"ingest_id": ingest_id}, {"processing.dependency_waits": 1}
        )
        stored = current.get("processing") if isinstance(current, dict) else {}
        waits = int((stored or {}).get("dependency_waits", 0)) + 1
        terminal = waits >= 100
        retry_at = None if terminal else now + timedelta(seconds=15)
        await self.mongo.raw_ingest.update_one(
            {"ingest_id": ingest_id},
            {
                "$set": {
                    "processing.status": "exhausted" if terminal else "waiting_dependency",
                    "processing.phase": "intel_saved",
                    "processing.intel_id": intel_id,
                    "processing.updated_at": now,
                    "processing.lease_expires_at": retry_at,
                    "processing.last_error": type(exc).__name__,
                },
                "$inc": {"processing.attempts": -1, "processing.dependency_waits": 1},
            },
        )
        logger.warning(
            "processor.waiting_dependency", ingest_id=ingest_id, error=type(exc).__name__
        )

    async def _release_open_leases(self) -> None:
        now = datetime.now(UTC)
        await self.mongo.raw_ingest.update_many(
            {"processing.status": "processing"},
            {
                "$set": {
                    "processing.status": "pending",
                    "processing.lease_expires_at": None,
                    "processing.updated_at": now,
                },
                "$inc": {"processing.attempts": -1},
            },
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
            audience = rule.get("audience", "viewer")

            if not enabled:
                continue
            if score < severity_min:
                continue
            if rule_products and not (rule_products & product_names):
                continue
            if rule_neighborhoods and neighborhood not in rule_neighborhoods:
                continue

            alert_doc: dict[str, Any] = {
                "_id": f"{record.intel_id}:{rule_name}",
                "rule_name": rule_name,
                "intel_id": record.intel_id,
                "triggered_at": datetime.now(UTC),
                "severity_score": score,
                "context": f"Rule '{rule_name}' triggered (Score {score} >= {severity_min})",
                "acknowledged": False,
                "assignee": None,
                "resolved_at": None,
                "audience": audience,
            }
            try:
                result = await self.mongo.alerts_history.insert_one(alert_doc)
            except DuplicateKeyError:
                continue
            alert_doc["id"] = str(result.inserted_id)
            alert_doc.pop("_id", None)
            alert_doc["triggered_at"] = alert_doc["triggered_at"].isoformat()
            try:
                await broadcast_alert(alert_doc)
            except Exception:
                logger.exception(
                    "processor.alert.broadcast_failed", intel_id=record.intel_id
                )
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
                term
                for term in watchlist.get("terms", [])
                if _term_in_text(str(term), observed)
            ]
            if not matches:
                continue
            alert_doc = {
                "_id": f"{record.intel_id}:watch:{watchlist.get('_id', '')}",
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
            try:
                result = await self.mongo.alerts_history.insert_one(alert_doc)
            except DuplicateKeyError:
                continue
            alert_doc["id"] = str(result.inserted_id)
            alert_doc.pop("_id", None)
            alert_doc["triggered_at"] = alert_doc["triggered_at"].isoformat()
            try:
                await broadcast_alert(alert_doc)
            except Exception:
                logger.exception(
                    "processor.alert.broadcast_failed", intel_id=record.intel_id
                )

    @property
    def healthy(self) -> bool:
        return self._fatal_error is None and self._task is not None and not self._task.done()
