from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from darkpulse.ingestion.hashing import canonical_json_bytes, sha256_hex
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType, CrawlMetadata, SourceClass

logger = logging.getLogger(__name__)

DATASET_NAME = "Evolution cryptomarket structured dataset"
DATASET_DOI = "10.5281/zenodo.10171217"
DATASET_LICENSE = "CC-BY-4.0"
MAX_TSV_FIELD_BYTES = 16 * 1024 * 1024

csv.field_size_limit(MAX_TSV_FIELD_BYTES)

REQUIRED_LISTING_COLUMNS = frozenset(
    {
        "lid",
        "vid",
        "mscrape_id",
        "title",
        "price",
        "description",
        "cid",
        "ships_from",
        "ships_to",
        "product_class",
        "listing_available",
        "return_policy",
    }
)


class EvolutionListingsLoader:
    def __init__(
        self,
        listings_path: Path,
        *,
        scrapes_path: Path | None = None,
    ) -> None:
        self._listings_path = listings_path
        self._scrapes_path = scrapes_path
        self._scrape_dates = self._load_scrape_dates(scrapes_path)

    @staticmethod
    def _load_scrape_dates(scrapes_path: Path | None) -> dict[str, datetime]:
        if scrapes_path is None or not scrapes_path.exists():
            return {}

        dates: dict[str, datetime] = {}
        with scrapes_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            expected = {"mscrape_id", "scrape_year", "scrape_month", "scrape_day"}
            missing = expected.difference(reader.fieldnames or [])
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(f"scrapes file is missing columns: {missing_text}")

            for row in reader:
                scrape_id = str(row["mscrape_id"]).strip()
                dates[scrape_id] = datetime(
                    int(float(str(row["scrape_year"]))),
                    int(float(str(row["scrape_month"]))),
                    int(float(str(row["scrape_day"]))),
                    tzinfo=UTC,
                )
        return dates

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        if not self._listings_path.exists():
            raise FileNotFoundError(self._listings_path)

        with self._listings_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            missing = REQUIRED_LISTING_COLUMNS.difference(reader.fieldnames or [])
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(f"listings file is missing columns: {missing_text}")

            for row_number, row in enumerate(reader, start=1):
                if limit is not None and row_number > limit:
                    break

                normalized_row = {
                    str(key): (None if value == "" else value)
                    for key, value in row.items()
                    if key is not None
                }
                identifiers = {
                    field: str(normalized_row.get(field) or "").strip()
                    for field in ("lid", "mscrape_id")
                }
                missing_identifiers = tuple(
                    field for field, value in identifiers.items() if not value
                )
                if missing_identifiers:
                    logger.warning(
                        "evolution_row_skipped_missing_identifier",
                        extra={
                            "event": "evolution_row_skipped_missing_identifier",
                            "dataset_row": row_number,
                            "missing_fields": missing_identifiers,
                        },
                    )
                    continue

                source_bytes = canonical_json_bytes(normalized_row)
                title_hash = sha256_hex(str(normalized_row.get("title") or "").encode("utf-8"))[:12]
                source_item_id = f"{identifiers['lid']}:{identifiers['mscrape_id']}:{title_hash}"
                source_ref = f"dataset://evolution/market/listings/{source_item_id}"
                payload = {
                    "dataset": {
                        "doi": DATASET_DOI,
                        "license": DATASET_LICENSE,
                        "name": DATASET_NAME,
                    },
                    "listing": normalized_row,
                    "record_type": "market_listing",
                }
                raw_content = canonical_json_bytes(payload).decode("utf-8")
                scrape_id = identifiers["mscrape_id"]

                yield SourceRecord(
                    source_class=SourceClass.DNM_DATASET,
                    source_ref=source_ref,
                    content_type=ContentType.JSON,
                    mime_type="application/json",
                    raw_content=raw_content,
                    source_bytes=source_bytes,
                    source_observed_at=self._scrape_dates.get(scrape_id),
                    crawl_metadata=CrawlMetadata(
                        source_item_id=source_item_id,
                        retries=0,
                    ),
                    source_metadata={
                        "canonicalization": "json-sort-keys-v1",
                        "dataset_doi": DATASET_DOI,
                        "dataset_license": DATASET_LICENSE,
                        "dataset_row": row_number,
                    },
                )
