from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from darkpulse.ingestion.loaders.evolution import EvolutionListingsLoader
from darkpulse.models import ContentType, SourceClass

FIXTURES = Path(__file__).parent / "fixtures"


def test_loader_emits_contract_ready_source_records() -> None:
    loader = EvolutionListingsLoader(
        FIXTURES / "evolution-listings.tsv",
        scrapes_path=FIXTURES / "evolution-scrapes.tsv",
    )

    records = list(loader.iter_records())

    assert len(records) == 2
    first = records[0]
    assert first.source_class is SourceClass.DNM_DATASET
    assert first.content_type is ContentType.JSON
    assert first.mime_type == "application/json"
    assert first.source_observed_at == datetime(2014, 1, 22, tzinfo=UTC)
    assert first.crawl_metadata.source_item_id is not None
    assert first.source_ref.startswith("dataset://evolution/market/listings/101:1:")

    payload = json.loads(first.raw_content)
    assert payload["record_type"] == "market_listing"
    assert payload["dataset"]["doi"] == "10.5281/zenodo.10171217"
    assert payload["listing"]["lid"] == "101"


def test_loader_honors_limit() -> None:
    loader = EvolutionListingsLoader(FIXTURES / "evolution-listings.tsv")
    assert len(list(loader.iter_records(limit=1))) == 1


@pytest.mark.parametrize("missing_field", ["lid", "mscrape_id"])
def test_loader_skips_rows_without_required_identifiers(
    tmp_path: Path,
    missing_field: str,
) -> None:
    fixture_lines = (FIXTURES / "evolution-listings.tsv").read_text(encoding="utf-8").splitlines()
    columns = fixture_lines[0].split("\t")
    invalid_row = fixture_lines[1].split("\t")
    invalid_row[columns.index(missing_field)] = ""

    listings_path = tmp_path / "listings.tsv"
    listings_path.write_text(
        "\n".join((fixture_lines[0], "\t".join(invalid_row), fixture_lines[2])) + "\n",
        encoding="utf-8",
    )

    records = list(EvolutionListingsLoader(listings_path).iter_records())

    assert len(records) == 1
    assert "None" not in records[0].crawl_metadata.source_item_id
