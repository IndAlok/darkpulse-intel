from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import CONTRACT_PATH, SAFETY_POLICY_PATH

from darkpulse.cli import async_main, build_parser, run_collect_all
from darkpulse.config import Settings
from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector, CollectorHealth, HealthStatus
from darkpulse.ingestion.collectors.registry import SourceRegistry
from darkpulse.ingestion.collectors.surface import validate_public_surface_url
from darkpulse.ingestion.live import SURFACE_SOURCE_CLASSES, CollectorHandle
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import SourceClass

REPO_SOURCES = Path(__file__).resolve().parents[1] / "config" / "sources.json"


class CliCollector(BaseCollector):
    def __init__(self, record: SourceRecord, source_id: str) -> None:
        super().__init__(
            source_id=source_id,
            source_class=SourceClass.SOCIAL,
            checkpoints=InMemoryCheckpointStore(),
        )
        self._record = record

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        yield self._record

    async def _health(self) -> CollectorHealth:
        return CollectorHealth.create(self.source_id, HealthStatus.HEALTHY)


def test_production_sources_are_public_https_or_disabled_datasets() -> None:
    registry = SourceRegistry.from_path(REPO_SOURCES)
    enabled = [source for source in registry.sources if source.enabled]
    assert enabled
    for source in enabled:
        assert source.source_class in SURFACE_SOURCE_CLASSES
        validate_public_surface_url(source.locator)
        assert ".onion" not in source.locator
    evolution = registry.get("evolution-primary")
    assert evolution.enabled is False
    assert evolution.source_class is SourceClass.DNM_DATASET
    assert registry.get("pib-press-releases").enabled is False


@pytest.mark.asyncio
async def test_collect_all_dry_run_skips_unsupported_and_summarizes(
    tmp_path, source_record, capsys, monkeypatch
) -> None:
    registry_path = tmp_path / "sources.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "evolution-primary",
                    "source_class": "dnm_dataset",
                    "enabled": True,
                    "locator": "/datasets/evolution",
                },
                {
                    "source_id": "news-a",
                    "source_class": "social",
                    "enabled": True,
                    "locator": "https://example.invalid/rss",
                },
                {
                    "source_id": "news-off",
                    "source_class": "social",
                    "enabled": False,
                    "locator": "https://example.invalid/off",
                },
            ]
        ),
        encoding="utf-8",
    )
    record = replace(
        source_record,
        source_class=SourceClass.SOCIAL,
        source_ref="https://example.invalid/rss",
    )
    close = AsyncMock()
    factory = AsyncMock(return_value=CollectorHandle(CliCollector(record, "news-a"), close))
    monkeypatch.setattr("darkpulse.cli.create_live_collector", factory)
    args = build_parser().parse_args(
        [
            "collect-all",
            "--sources",
            str(registry_path),
            "--dry-run",
            "--source-gap",
            "0",
            "--contract",
            str(CONTRACT_PATH),
            "--safety-policy",
            str(SAFETY_POLICY_PATH),
        ]
    )

    exit_code = await run_collect_all(args, Settings())
    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["command"] == "collect-all"
    assert summary["dry_run"] is True
    by_id = {item["source_id"]: item for item in summary["runs"]}
    assert by_id["evolution-primary"]["failure_code"] == "unsupported_live_class"
    assert by_id["evolution-primary"]["skipped"] is True
    assert by_id["news-a"]["published"] == 1
    assert "news-off" not in by_id
    assert "example.invalid" not in json.dumps(summary)
    close.assert_awaited_once()
    factory.assert_awaited_once()


@pytest.mark.asyncio
async def test_collect_all_setup_failure_is_content_free(capsys, tmp_path) -> None:
    source_path = tmp_path / "sources.json"
    source_path.write_text("not-json", encoding="utf-8")
    exit_code = await async_main(
        ["collect-all", "--sources", str(source_path), "--dry-run", "--source-gap", "0"]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(captured.err)
    assert payload["failure_code"] == "setup_failed"
    assert payload["error_type"] == "JSONDecodeError"
