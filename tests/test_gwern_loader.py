from pathlib import Path

import pytest

from darkpulse.ingestion.extraction import html_to_text
from darkpulse.ingestion.loaders.gwern import GwernArchiveLoader
from darkpulse.models import ContentType, SourceClass

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "gwern"


def test_gwern_loader_reads_selected_csv_tsv_and_static_html() -> None:
    records = list(GwernArchiveLoader(FIXTURE_ROOT).iter_records())

    assert len(records) == 3
    assert {record.content_type for record in records} == {ContentType.HTML, ContentType.JSON}
    assert all(record.source_class is SourceClass.DNM_DATASET for record in records)
    assert all(record.source_ref.startswith("dataset://gwern/") for record in records)
    assert {record.source_metadata["market"] for record in records} == {
        "agora",
        "evolution",
        "silk-road",
    }


def test_gwern_loader_filters_markets_and_honors_limit() -> None:
    records = list(
        GwernArchiveLoader(
            FIXTURE_ROOT,
            markets=frozenset({"Evolution"}),
            max_records=1,
        ).iter_records()
    )

    assert len(records) == 1
    assert records[0].source_metadata["market"] == "evolution"


def test_gwern_html_parser_never_includes_active_content() -> None:
    text = html_to_text(
        b"<style>sensitive style</style><script>sensitive script</script><p>visible text</p>"
    )

    assert text == "visible text"


def test_gwern_loader_requires_existing_directory(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        list(GwernArchiveLoader(tmp_path / "missing").iter_records())


def test_gwern_loader_skips_symlinks(tmp_path) -> None:
    market = tmp_path / "agora"
    market.mkdir()
    target = market / "source.html"
    target.write_text("<p>fixture</p>", encoding="utf-8")
    try:
        (market / "linked.html").symlink_to(target)
    except OSError:
        pytest.skip("symlink privilege unavailable")

    records = list(GwernArchiveLoader(tmp_path).iter_records())

    assert len(records) == 1
