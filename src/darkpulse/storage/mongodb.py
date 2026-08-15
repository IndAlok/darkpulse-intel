from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

from darkpulse.config import MongoSettings

logger = structlog.get_logger(__name__)


def language_match(lang: str) -> dict[str, Any]:
    if lang.casefold() == "hinglish":
        return {
            "$or": [
                {"language.detected": "hinglish"},
                {"language.code_mixed": True},
                {"language.romanized": True},
            ]
        }
    return {"language.detected": lang}


def _redact_uri(uri: str) -> str:
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(uri)
        if parsed.username or parsed.password:
            host = parsed.hostname or ""
            if parsed.port:
                host = f"{host}:{parsed.port}"
            return f"{parsed.scheme}://<redacted>@{host}{parsed.path}"
        return uri
    except ValueError:
        return "<unparseable-uri>"


class MongoManager:
    def __init__(self, settings: MongoSettings) -> None:
        self._settings = settings
        self._client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]
        self._db: AsyncIOMotorDatabase | None = None  # type: ignore[type-arg]

    async def connect(self) -> None:
        logger.info("mongodb.connecting", uri=_redact_uri(self._settings.uri))
        self._client = AsyncIOMotorClient(
            self._settings.uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self._db = self._client[self._settings.database]

        await self._client.admin.command("ping")
        logger.info("mongodb.connected", database=self._settings.database)

        if self._settings.skip_index_ensure:
            logger.info("mongodb.indexes_skipped")
            return
        try:
            await self._ensure_indexes()
        except Exception as exc:
            logger.warning(
                "mongodb.indexes_failed",
                error_type=type(exc).__name__,
                error_code=getattr(exc, "code", None),
            )

    async def close(self) -> None:
        if self._client:
            self._client.close()
            logger.info("mongodb.disconnected")

    async def health(self) -> dict[str, str | int]:
        if not self._client:
            return {"status": "disconnected"}
        try:
            import time

            start = time.monotonic()
            await self._client.admin.command("ping")
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"status": "healthy", "latency_ms": latency_ms}
        except Exception:
            return {"status": "unhealthy"}

    async def ensure_application_defaults(self, slang_seed_path: str | Path) -> None:
        from darkpulse.nlp.slang import SlangDictionary

        dictionary = SlangDictionary()
        dictionary.load_seed(slang_seed_path)
        for term in dictionary.terms:
            entry = dictionary.get_entry(term)
            if entry is None:
                continue
            await self.slang.update_one(
                {"_id": f"{entry.language}:{entry.term}"},
                {
                    "$setOnInsert": {
                        "term": entry.term,
                        "meaning": entry.canonical,
                        "lang": entry.language,
                        "confidence": entry.confidence,
                        "newly_discovered": False,
                        "review_status": "approved",
                        "source": entry.source,
                    }
                },
                upsert=True,
            )

        await self.alerts_config.update_one(
            {"_id": "default"},
            {
                "$setOnInsert": {
                    "rules": [
                        {
                            "name": "High local severity",
                            "severity_min": 60,
                            "products": [],
                            "neighborhoods": [],
                            "enabled": True,
                        }
                    ]
                }
            },
            upsert=True,
        )

    @property
    def db(self) -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
        if self._db is None:
            msg = "MongoDB not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._db

    @property
    def raw_ingest(self) -> Any:  # noqa: ANN201
        return self.db[self._settings.raw_ingest_collection]

    @property
    def intel(self) -> Any:
        return self.db[self._settings.intel_collection]

    @property
    def watchlists(self) -> Any:
        return self.db[self._settings.watchlists_collection]

    @property
    def slang(self) -> Any:
        return self.db[self._settings.slang_collection]

    @property
    def alerts_config(self) -> Any:
        return self.db[self._settings.alerts_config_collection]

    @property
    def alerts_history(self) -> Any:
        return self.db[self._settings.alerts_history_collection]

    @property
    def evidence(self) -> Any:  # noqa: ANN201
        return self.db[self._settings.evidence_collection]

    @property
    def audit(self) -> Any:  # noqa: ANN201
        return self.db[self._settings.audit_collection]

    @property
    def collection_runs(self) -> Any:  # noqa: ANN201
        return self.db[self._settings.collection_runs_collection]

    async def search_intel(
        self,
        query: str,
        *,
        limit: int = 50,
        lang: str | None = None,
    ) -> dict[str, Any]:
        from darkpulse.api.search_query import expand_search_terms, extract_intel_id

        safe_limit = max(1, min(limit, 200))
        intel_id = extract_intel_id(query)
        if intel_id:
            doc = await self.intel.find_one({"intel_id": intel_id}, {"_id": 0})
            return {"total": 1 if doc else 0, "records": [doc] if doc else []}

        terms = expand_search_terms(query)
        try:
            merged = await MongoManager._merge_slang_synonyms(self, terms)
            if isinstance(merged, list) and merged:
                terms = merged
        except Exception:
            pass
        text_query = " ".join(terms)
        match: dict[str, Any] = {"$text": {"$search": text_query}}
        if lang:
            match = {"$and": [match, language_match(lang)]}
        pipeline: list[dict[str, Any]] = [
            {"$match": match},
            {"$addFields": {"text_score": {"$meta": "textScore"}}},
            {"$sort": {"severity.score": -1, "text_score": -1, "_id": -1}},
            {"$limit": safe_limit},
            {"$unset": "_id"},
        ]
        try:
            docs = await self.intel.aggregate(pipeline).to_list(length=safe_limit)
            if docs:
                total = await self.intel.count_documents(match)
                return {"total": total, "records": docs}
        except OperationFailure as exc:
            if exc.code != 27:
                raise
            logger.warning("mongodb.text_index_missing")
        return await self._search_intel_fallback(terms, lang=lang, limit=safe_limit)

    async def _merge_slang_synonyms(self, terms: list[str]) -> list[str]:
        extras: list[str] = []
        try:
            clauses = [
                {"term": {"$regex": f"^{re.escape(term)}$", "$options": "i"}}
                for term in terms[:8]
                if len(term) >= 2
            ]
            clauses.extend(
                {"meaning": {"$regex": re.escape(term), "$options": "i"}}
                for term in terms[:8]
                if len(term) >= 3
            )
            if not clauses:
                return terms
            docs = await self.slang.find(
                {
                    "$and": [
                        {"$or": clauses},
                        {"review_status": {"$ne": "rejected"}},
                    ]
                },
                {"term": 1, "meaning": 1, "_id": 0},
            ).to_list(length=40)
        except Exception:
            return terms
        if not isinstance(docs, list):
            return terms
        for doc in docs:
            extras.append(str(doc.get("term") or ""))
            extras.append(str(doc.get("meaning") or ""))
        merged: list[str] = []
        seen: set[str] = set()
        for term in [*terms, *extras]:
            key = term.casefold().strip()
            if key and key not in seen:
                seen.add(key)
                merged.append(term.strip())
        return merged[:16]

    async def _search_intel_fallback(
        self,
        query: str | list[str],
        *,
        lang: str | None,
        limit: int,
    ) -> dict[str, Any]:
        terms = query if isinstance(query, list) else [query]
        clauses: list[dict[str, Any]] = []
        for term in terms:
            escaped = re.escape(term)
            clauses.extend(
                [
                    {"intel_id": {"$regex": escaped, "$options": "i"}},
                    {"translated_text": {"$regex": escaped, "$options": "i"}},
                    {"products.canonical": {"$regex": escaped, "$options": "i"}},
                    {"products.raw_term": {"$regex": escaped, "$options": "i"}},
                    {"slang_decoded.term": {"$regex": escaped, "$options": "i"}},
                    {"slang_decoded.meaning": {"$regex": escaped, "$options": "i"}},
                    {"tags": {"$regex": escaped, "$options": "i"}},
                    {"entities.vendors.alias": {"$regex": escaped, "$options": "i"}},
                    {"geo.neighborhood": {"$regex": escaped, "$options": "i"}},
                    {"geo.city": {"$regex": escaped, "$options": "i"}},
                    {"evidence_snapshot.excerpt": {"$regex": escaped, "$options": "i"}},
                    {"intent.label": {"$regex": escaped, "$options": "i"}},
                ]
            )
        match: dict[str, Any] = {"$or": clauses}
        if lang:
            match = {"$and": [match, language_match(lang)]}
        docs = await self.intel.find(match, {"_id": 0}).sort("severity.score", -1).to_list(
            length=limit
        )
        total = await self.intel.count_documents(match)
        return {"total": total, "records": docs}

    async def _create_index(self, collection: Any, *args: Any, **kwargs: Any) -> None:
        try:
            await collection.create_index(*args, **kwargs)
        except Exception as exc:
            logger.warning(
                "mongodb.index_ensure_skipped",
                index=str(kwargs.get("name") or (args[0] if args else "index")),
                error_type=type(exc).__name__,
                error_code=getattr(exc, "code", None),
            )

    async def _ensure_indexes(self) -> None:
        await self._create_index(self.raw_ingest, "dedup_key", unique=True)
        await self._create_index(self.raw_ingest, "ingest_id")
        await self._create_index(self.raw_ingest, "source_class")
        await self._create_index(
            self.raw_ingest, "processing.status", name="raw_ingest_processing_status"
        )
        await self._create_index(
            self.raw_ingest, "processing.lease_expires_at", name="raw_ingest_processing_lease"
        )

        await self._create_index(self.intel, "intel_id", unique=True)
        await self._create_index(self.intel, "ingest_id")
        await self._create_index(self.intel, "captured_at")
        await self._create_index(
            self.intel, [("captured_at", -1), ("intel_id", -1)], name="intel_captured_at_intel_id"
        )
        await self._create_index(self.intel, "severity.band")
        await self._create_index(self.intel, "severity.score")
        await self._create_index(self.intel, "source_class")
        await self._create_index(self.intel, "intent.label")
        await self._create_index(self.intel, "geo.neighborhood")
        await self._create_index(self.intel, "entities.vendors.alias")
        existing_indexes = await self.intel.index_information()
        if "intel_text_search" not in existing_indexes:
            await self._create_index(
                self.intel,
                [
                    ("translated_text", "text"),
                    ("products.canonical", "text"),
                    ("products.raw_term", "text"),
                    ("slang_decoded.term", "text"),
                    ("slang_decoded.meaning", "text"),
                    ("tags", "text"),
                    ("geo.neighborhood", "text"),
                    ("evidence_snapshot.excerpt", "text"),
                ],
                name="intel_text_search",
                default_language="english",
                language_override="language_override",
            )

        await self._create_index(
            self.raw_ingest, "captured_at", expireAfterSeconds=86400, name="ttl_raw_ingest"
        )
        await self._create_index(
            self.alerts_history,
            "triggered_at",
            expireAfterSeconds=2592000,
            name="ttl_alerts_history",
        )
        await self._create_index(self.audit, "occurred_at", name="audit_occurred_at")
        await self._create_index(
            self.audit, [("actor", 1), ("occurred_at", -1)], name="audit_actor_time"
        )
        await self._create_index(
            self.evidence, "hash_sha256", unique=True, name="evidence_hash_unique"
        )
        await self._create_index(
            self.collection_runs, "started_at", name="collection_runs_started_at"
        )
        await self._create_index(
            self.collection_runs, "source_id", name="collection_runs_source_id"
        )

        logger.info("mongodb.indexes_ensured")
