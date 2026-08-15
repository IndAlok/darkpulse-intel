from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import CONTRACT_PATH, SAFETY_POLICY_PATH

from darkpulse.cli import async_main, build_parser, run_live_collection
from darkpulse.config import Settings
from darkpulse.ingestion.checkpoints import InMemoryCheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector, CollectorHealth, HealthStatus
from darkpulse.ingestion.live import CollectorHandle
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import SourceClass

FIXTURES = Path(__file__).parent / "fixtures"


class CliCollector(BaseCollector):
    def __init__(self, record: SourceRecord) -> None:
        super().__init__(
            source_id="surface-a",
            source_class=SourceClass.SURFACE_MARKET,
            checkpoints=InMemoryCheckpointStore(),
        )
        self._record = record

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        yield self._record

    async def _health(self) -> CollectorHealth:
        return CollectorHealth.create(self.source_id, HealthStatus.HEALTHY)


@pytest.mark.asyncio
async def test_evolution_dry_run_reports_counts_without_content(capsys) -> None:
    exit_code = await async_main(
        [
            "evolution",
            "--input",
            str(FIXTURES / "evolution-listings.tsv"),
            "--scrapes",
            str(FIXTURES / "evolution-scrapes.tsv"),
            "--limit",
            "1",
            "--dry-run",
            "--contract",
            str(CONTRACT_PATH),
            "--safety-policy",
            str(SAFETY_POLICY_PATH),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert exit_code == 0
    assert summary["counts"] == {"published": 1}
    assert "Fixture description" not in captured.out
    assert "Fixture description" not in captured.err
    assert captured.err == ""


@pytest.mark.asyncio
async def test_gwern_dry_run_filters_markets_and_reports_counts(capsys) -> None:
    exit_code = await async_main(
        [
            "gwern",
            "--input",
            str(FIXTURES / "gwern"),
            "--market",
            "silk-road",
            "--limit",
            "1",
            "--dry-run",
            "--contract",
            str(CONTRACT_PATH),
            "--safety-policy",
            str(SAFETY_POLICY_PATH),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert exit_code == 0
    assert summary == {
        "command": "gwern",
        "counts": {"published": 1},
        "dry_run": True,
    }
    assert "Silk Road fixture" not in captured.out
    assert captured.err == ""


@pytest.mark.asyncio
async def test_live_dry_run_uses_registry_pipeline_and_content_free_summary(
    tmp_path,
    source_record,
    capsys,
    monkeypatch,
) -> None:
    registry_path = tmp_path / "sources.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "surface-a",
                    "source_class": "surface_market",
                    "enabled": True,
                    "locator": "https://example.invalid/source",
                }
            ]
        ),
        encoding="utf-8",
    )
    record = replace(
        source_record,
        source_class=SourceClass.SURFACE_MARKET,
        source_ref="https://example.invalid/source",
    )
    close = AsyncMock()
    factory = AsyncMock(return_value=CollectorHandle(CliCollector(record), close))
    monkeypatch.setattr("darkpulse.cli.create_live_collector", factory)
    args = build_parser().parse_args(
        [
            "collect",
            "--source-id",
            "surface-a",
            "--sources",
            str(registry_path),
            "--dry-run",
            "--contract",
            str(CONTRACT_PATH),
            "--safety-policy",
            str(SAFETY_POLICY_PATH),
        ]
    )

    exit_code = await run_live_collection(args, Settings())

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["summary"]["published"] == 1
    assert "Fixture text" not in json.dumps(summary)
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_auth_missing_credentials_is_content_free(capsys, monkeypatch) -> None:
    monkeypatch.delenv("DARKPULSE_TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("DARKPULSE_TELEGRAM_API_HASH", raising=False)

    exit_code = await async_main(["telegram-auth"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["failure_code"] == "credentials_not_configured"


@pytest.mark.asyncio
async def test_collect_setup_failure_does_not_print_configuration(capsys, tmp_path) -> None:
    source_path = tmp_path / "sources.json"
    sensitive_locator = "https://example.invalid/source?token=sensitive-value"
    source_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "surface-a",
                    "source_class": "surface_market",
                    "enabled": True,
                    "locator": sensitive_locator,
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = await async_main(
        [
            "collect",
            "--source-id",
            "surface-a",
            "--sources",
            str(source_path),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert sensitive_locator not in captured.err
    assert json.loads(captured.err)["failure_code"] == "setup_failed"
