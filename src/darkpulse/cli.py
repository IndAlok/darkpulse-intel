from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import asdict
from pathlib import Path

from darkpulse.config import Settings, get_settings
from darkpulse.ingestion.checkpoints import (
    CheckpointStore,
    InMemoryCheckpointStore,
    RedisCheckpointStore,
)
from darkpulse.ingestion.collectors.registry import SourceRegistry
from darkpulse.ingestion.collectors.runner import CollectorRunner, CollectorRunSummary
from darkpulse.ingestion.collectors.telegram import bootstrap_telegram_session
from darkpulse.ingestion.content_state import (
    ContentStateStore,
    InMemoryContentStateStore,
    RedisContentStateStore,
)
from darkpulse.ingestion.dedup import DedupStore, InMemoryDedupStore, RedisDedupStore
from darkpulse.ingestion.live import (
    SURFACE_SOURCE_CLASSES,
    LiveSourceConfig,
    create_live_collector,
)
from darkpulse.ingestion.loaders.evolution import EvolutionListingsLoader
from darkpulse.ingestion.loaders.gwern import GwernArchiveLoader
from darkpulse.ingestion.logging import configure_logging
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.pipeline import IngestionPipeline
from darkpulse.ingestion.publisher import InMemoryPublisher, MongoPublisher, RecordPublisher
from darkpulse.ingestion.safety import SafetyPolicy
from darkpulse.ingestion.validation import ContractValidator
from darkpulse.storage.mongodb import MongoManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="darkpulse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    evolution = subparsers.add_parser("evolution", help="Load Evolution listings TSV records.")
    evolution.add_argument("--input", required=True, type=Path)
    evolution.add_argument("--scrapes", type=Path)
    evolution.add_argument("--limit", type=int)
    evolution.add_argument("--dry-run", action="store_true")
    evolution.add_argument("--contract", type=Path)
    evolution.add_argument("--safety-policy", type=Path)

    gwern = subparsers.add_parser("gwern", help="Load selected pre-extracted Gwern subsets.")
    gwern.add_argument("--input", required=True, type=Path)
    gwern.add_argument("--market", action="append", default=[])
    gwern.add_argument("--limit", type=int)
    gwern.add_argument("--dry-run", action="store_true")
    gwern.add_argument("--contract", type=Path)
    gwern.add_argument("--safety-policy", type=Path)

    collect = subparsers.add_parser("collect", help="Run one enabled approved live source.")
    collect.add_argument("--source-id", required=True)
    collect.add_argument("--sources", type=Path)
    collect.add_argument("--onion-review", type=Path)
    collect.add_argument("--dry-run", action="store_true")
    collect.add_argument("--contract", type=Path)
    collect.add_argument("--safety-policy", type=Path)

    collect_all = subparsers.add_parser(
        "collect-all",
        help="Run every enabled public HTTPS source once, or loop on an interval.",
    )
    collect_all.add_argument("--sources", type=Path)
    collect_all.add_argument("--onion-review", type=Path)
    collect_all.add_argument("--dry-run", action="store_true")
    collect_all.add_argument("--contract", type=Path)
    collect_all.add_argument("--safety-policy", type=Path)
    collect_all.add_argument("--loop", action="store_true")
    collect_all.add_argument("--interval", type=int, default=300)
    collect_all.add_argument("--source-gap", type=float, default=2.0)

    subparsers.add_parser("telegram-auth", help="Create or refresh the operator Telegram session.")

    return parser


def _pipeline_resources(
    settings: Settings,
    dry_run: bool,
    contract_path: Path,
    safety_policy_path: Path,
    metrics: IngestionMetrics,
) -> tuple[IngestionPipeline, RecordPublisher, DedupStore, MongoManager | None]:
    publisher: RecordPublisher
    dedup_store: DedupStore
    mongo_manager: MongoManager | None
    if dry_run:
        publisher = InMemoryPublisher()
        dedup_store = InMemoryDedupStore()
        mongo_manager = None
    else:
        mongo_manager = MongoManager(settings.mongo)
        publisher = MongoPublisher(mongo_manager)
        dedup_store = RedisDedupStore(
            settings.redis.url,
            ttl_seconds=settings.collection.dedup_ttl_seconds,
        )

    pipeline = IngestionPipeline(
        safety_policy=SafetyPolicy.from_path(safety_policy_path),
        dedup_store=dedup_store,
        publisher=publisher,
        validator=ContractValidator(contract_path),
        metrics=metrics,
        collector_id=settings.collection.collector_id,
        collector_version=settings.collection.collector_version,
    )
    return pipeline, publisher, dedup_store, mongo_manager


async def run_evolution(args: argparse.Namespace, settings: Settings) -> int:
    contract_path = args.contract or settings.collection.contract_path
    safety_policy_path = args.safety_policy or settings.collection.safety_policy_path
    metrics = IngestionMetrics()
    pipeline, publisher, dedup_store, mongo_manager = _pipeline_resources(
        settings, args.dry_run, contract_path, safety_policy_path, metrics
    )
    loader = EvolutionListingsLoader(args.input, scrapes_path=args.scrapes)
    counts: Counter[str] = Counter()

    publisher_started = False
    try:
        if mongo_manager is not None:
            await mongo_manager.connect()
        await publisher.start()
        publisher_started = True
        for record in loader.iter_records(limit=args.limit):
            outcome = await pipeline.process(record)
            counts[outcome.status.value] += 1
    finally:
        try:
            if publisher_started:
                await publisher.stop()
        finally:
            await dedup_store.close()
        if mongo_manager is not None:
            await mongo_manager.close()

    print(
        json.dumps(
            {
                "command": "evolution",
                "dry_run": bool(args.dry_run),
                "counts": dict(sorted(counts.items())),
            },
            sort_keys=True,
        )
    )
    return 0


async def run_gwern(args: argparse.Namespace, settings: Settings) -> int:
    contract_path = args.contract or settings.collection.contract_path
    safety_policy_path = args.safety_policy or settings.collection.safety_policy_path
    metrics = IngestionMetrics()
    pipeline, publisher, dedup_store, mongo_manager = _pipeline_resources(
        settings, args.dry_run, contract_path, safety_policy_path, metrics
    )
    loader = GwernArchiveLoader(args.input, markets=frozenset(args.market), max_records=args.limit)
    counts: Counter[str] = Counter()

    publisher_started = False
    try:
        if mongo_manager is not None:
            await mongo_manager.connect()
        await publisher.start()
        publisher_started = True
        for record in loader.iter_records():
            outcome = await pipeline.process(record)
            counts[outcome.status.value] += 1
    finally:
        try:
            if publisher_started:
                await publisher.stop()
        finally:
            await dedup_store.close()
        if mongo_manager is not None:
            await mongo_manager.close()

    print(
        json.dumps(
            {
                "command": "gwern",
                "dry_run": bool(args.dry_run),
                "counts": dict(sorted(counts.items())),
            },
            sort_keys=True,
        )
    )
    return 0


async def run_live_collection(args: argparse.Namespace, settings: Settings) -> int:
    registry = SourceRegistry.from_path(args.sources or settings.collection.sources_path)
    source = registry.get(args.source_id)
    metrics = IngestionMetrics()
    pipeline, publisher, dedup_store, mongo_manager = _pipeline_resources(
        settings,
        args.dry_run,
        args.contract or settings.collection.contract_path,
        args.safety_policy or settings.collection.safety_policy_path,
        metrics,
    )

    checkpoints: CheckpointStore
    content_state: ContentStateStore
    if args.dry_run:
        checkpoints = InMemoryCheckpointStore()
        content_state = InMemoryContentStateStore()
    else:
        checkpoints = RedisCheckpointStore(settings.redis.url)
        content_state = RedisContentStateStore(settings.redis.url)

    api_hash = (
        settings.collection.telegram_api_hash.get_secret_value()
        if settings.collection.telegram_api_hash
        else None
    )
    live_config = LiveSourceConfig(
        onion_review_policy_path=args.onion_review or settings.collection.onion_review_policy_path,
        tor_proxy_url=settings.collection.tor_proxy_url,
        telegram_api_id=settings.collection.telegram_api_id,
        telegram_api_hash=api_hash,
        telegram_runtime_root=settings.collection.telegram_runtime_root,
        telegram_session_path=settings.collection.telegram_session_path,
        telegram_max_messages=settings.collection.telegram_max_messages,
    )

    async with AsyncExitStack() as stack:
        stack.push_async_callback(dedup_store.close)
        stack.push_async_callback(checkpoints.close)
        stack.push_async_callback(content_state.close)
        if mongo_manager is not None:
            await mongo_manager.connect()
            stack.push_async_callback(mongo_manager.close)
        handle = await create_live_collector(
            source=source,
            config=live_config,
            checkpoints=checkpoints,
            content_state=content_state,
        )
        stack.push_async_callback(handle.close)
        await publisher.start()
        stack.push_async_callback(publisher.stop)
        summary = await CollectorRunner(pipeline, metrics=metrics).run(handle.collector)

    print(
        json.dumps(
            {"command": "collect", "dry_run": bool(args.dry_run), "summary": asdict(summary)},
            sort_keys=True,
        )
    )
    return 1 if summary.failures else 0


def _live_config(args: argparse.Namespace, settings: Settings) -> LiveSourceConfig:
    api_hash = (
        settings.collection.telegram_api_hash.get_secret_value()
        if settings.collection.telegram_api_hash
        else None
    )
    return LiveSourceConfig(
        onion_review_policy_path=args.onion_review or settings.collection.onion_review_policy_path,
        tor_proxy_url=settings.collection.tor_proxy_url,
        telegram_api_id=settings.collection.telegram_api_id,
        telegram_api_hash=api_hash,
        telegram_runtime_root=settings.collection.telegram_runtime_root,
        telegram_session_path=settings.collection.telegram_session_path,
        telegram_max_messages=settings.collection.telegram_max_messages,
    )


async def _persist_collection_run(
    mongo_manager: MongoManager | None,
    *,
    source_id: str,
    started_at: object,
    summary: object,
    skipped: bool = False,
) -> None:
    if mongo_manager is None:
        return
    from datetime import UTC, datetime

    payload = {
        "source_id": source_id,
        "started_at": started_at,
        "finished_at": datetime.now(UTC),
        "published": getattr(summary, "published", 0),
        "duplicates": getattr(summary, "duplicates", 0),
        "rejected": getattr(summary, "rejected", 0),
        "failures": getattr(summary, "failures", 0),
        "failure_code": getattr(summary, "failure_code", None),
        "skipped": skipped,
    }
    await mongo_manager.collection_runs.insert_one(payload)


async def run_collect_all(args: argparse.Namespace, settings: Settings) -> int:
    from datetime import UTC, datetime

    registry = SourceRegistry.from_path(args.sources or settings.collection.sources_path)
    interval = max(30, int(args.interval))
    source_gap = max(0.0, float(args.source_gap))
    metrics = IngestionMetrics()
    pipeline, publisher, dedup_store, mongo_manager = _pipeline_resources(
        settings,
        args.dry_run,
        args.contract or settings.collection.contract_path,
        args.safety_policy or settings.collection.safety_policy_path,
        metrics,
    )
    if args.dry_run:
        checkpoints: CheckpointStore = InMemoryCheckpointStore()
        content_state: ContentStateStore = InMemoryContentStateStore()
    else:
        checkpoints = RedisCheckpointStore(settings.redis.url)
        content_state = RedisContentStateStore(settings.redis.url)
    live_config = _live_config(args, settings)
    cycle_exit = 0

    async with AsyncExitStack() as stack:
        stack.push_async_callback(dedup_store.close)
        stack.push_async_callback(checkpoints.close)
        stack.push_async_callback(content_state.close)
        if mongo_manager is not None:
            await mongo_manager.connect()
            stack.push_async_callback(mongo_manager.close)
        await publisher.start()
        stack.push_async_callback(publisher.stop)
        runner = CollectorRunner(pipeline, metrics=metrics)

        while True:
            cycle: list[dict[str, object]] = []
            for source in registry.sources:
                if not source.enabled:
                    continue
                started_at = datetime.now(UTC)
                if source.source_class not in SURFACE_SOURCE_CLASSES:
                    skipped = {
                        "source_id": source.source_id,
                        "published": 0,
                        "duplicates": 0,
                        "rejected": 0,
                        "failures": 0,
                        "failure_code": "unsupported_live_class",
                        "skipped": True,
                    }
                    cycle.append(skipped)
                    await _persist_collection_run(
                        mongo_manager,
                        source_id=source.source_id,
                        started_at=started_at,
                        summary=type("S", (), skipped)(),
                        skipped=True,
                    )
                    continue
                try:
                    handle = await create_live_collector(
                        source=source,
                        config=live_config,
                        checkpoints=checkpoints,
                        content_state=content_state,
                    )
                    try:
                        summary = await runner.run(handle.collector)
                    finally:
                        await handle.close()
                except Exception:
                    summary = CollectorRunSummary(
                        source_id=source.source_id,
                        failures=1,
                        failure_code="setup_failed",
                    )
                cycle.append(asdict(summary))
                await _persist_collection_run(
                    mongo_manager,
                    source_id=source.source_id,
                    started_at=started_at,
                    summary=summary,
                )
                if source_gap:
                    await asyncio.sleep(source_gap)
            failures = sum(int(item.get("failures") or 0) for item in cycle)
            cycle_exit = 1 if failures else 0
            print(
                json.dumps(
                    {
                        "command": "collect-all",
                        "dry_run": bool(args.dry_run),
                        "interval": interval,
                        "runs": cycle,
                    },
                    sort_keys=True,
                    default=str,
                )
            )
            if not args.loop:
                return cycle_exit
            await asyncio.sleep(interval)

    return cycle_exit


async def run_telegram_auth(settings: Settings) -> int:
    api_hash = (
        settings.collection.telegram_api_hash.get_secret_value()
        if settings.collection.telegram_api_hash
        else None
    )
    if settings.collection.telegram_api_id is None or not api_hash:
        print(
            json.dumps(
                {
                    "command": "telegram-auth",
                    "failure_code": "credentials_not_configured",
                    "status": "failed",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    await bootstrap_telegram_session(
        session_path=settings.collection.telegram_session_path,
        runtime_root=settings.collection.telegram_runtime_root,
        api_id=settings.collection.telegram_api_id,
        api_hash=api_hash,
    )
    print(json.dumps({"command": "telegram-auth", "status": "authorized"}, sort_keys=True))
    return 0


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.service.log_level)
    if args.command == "evolution":
        return await run_evolution(args, settings)
    if args.command == "gwern":
        return await run_gwern(args, settings)
    if args.command == "collect":
        try:
            return await run_live_collection(args, settings)
        except Exception:
            print(
                json.dumps(
                    {"command": "collect", "failure_code": "setup_failed", "status": "failed"},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    if args.command == "collect-all":
        try:
            return await run_collect_all(args, settings)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "command": "collect-all",
                        "error_code": getattr(exc, "code", None),
                        "error_type": type(exc).__name__,
                        "failure_code": "setup_failed",
                        "status": "failed",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    if args.command == "telegram-auth":
        try:
            return await run_telegram_auth(settings)
        except Exception:
            print(
                json.dumps(
                    {
                        "command": "telegram-auth",
                        "failure_code": "authorization_failed",
                        "status": "failed",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
