from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from darkpulse.ingestion.extraction import html_to_text
from darkpulse.ingestion.hashing import canonical_json_bytes, sha256_hex
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType, CrawlMetadata, SourceClass

logger = logging.getLogger(__name__)

DATASET_NAME = "Gwern Dark Net Market Archives"
DATASET_REFERENCE = "https://archive.org/details/dnmarchives"
MAX_TABULAR_FILE_BYTES = 50 * 1024 * 1024
MAX_FIELD_BYTES = 16 * 1024 * 1024
SUPPORTED_SUFFIXES = frozenset({".csv", ".htm", ".html", ".tsv"})

csv.field_size_limit(MAX_FIELD_BYTES)


class GwernArchiveLoader:
    def __init__(
        self,
        root: Path,
        *,
        markets: frozenset[str] | None = None,
        max_records: int | None = None,
        max_html_bytes: int = 2_000_000,
    ) -> None:
        self._root = root
        self._markets = frozenset(market.casefold() for market in markets or ())
        self._max_records = max_records
        self._max_html_bytes = max_html_bytes
        if max_records is not None and max_records < 0:
            raise ValueError("max_records cannot be negative")
        if not 1 <= max_html_bytes <= 2_000_000:
            raise ValueError("max_html_bytes must be between 1 and 2000000")

    def iter_records(self) -> Iterator[SourceRecord]:
        if not self._root.is_dir():
            raise FileNotFoundError("Gwern subset directory does not exist")

        emitted = 0
        for path in sorted(self._root.rglob("*")):
            if self._max_records is not None and emitted >= self._max_records:
                break
            if not self._is_approved_file(path):
                continue
            remaining = None if self._max_records is None else self._max_records - emitted
            for record in self._records_from_path(path, remaining=remaining):
                yield record
                emitted += 1

    def _is_approved_file(self, path: Path) -> bool:
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix.casefold() not in SUPPORTED_SUFFIXES
        ):
            return False
        relative = path.relative_to(self._root)
        if not relative.parts:
            return False
        market = relative.parts[0].casefold() if len(relative.parts) > 1 else "unclassified"
        return not self._markets or market in self._markets

    def _records_from_path(
        self,
        path: Path,
        *,
        remaining: int | None,
    ) -> Iterator[SourceRecord]:
        suffix = path.suffix.casefold()
        if suffix in {".html", ".htm"}:
            record = self._html_record(path)
            if record is not None and remaining != 0:
                yield record
            return
        yield from self._tabular_records(
            path,
            delimiter="\t" if suffix == ".tsv" else ",",
            remaining=remaining,
        )

    def _html_record(self, path: Path) -> SourceRecord | None:
        try:
            with path.open("rb") as handle:
                source_bytes = handle.read(self._max_html_bytes + 1)
        except OSError:
            return None
        if len(source_bytes) > self._max_html_bytes:
            logger.warning("gwern.html_file_too_large path=%s", path)
            return None
        raw_content = html_to_text(source_bytes)
        if not raw_content:
            return None
        return self._record(
            path,
            source_bytes=source_bytes,
            raw_content=raw_content,
            content_type=ContentType.HTML,
            mime_type="text/html",
            source_item_id=sha256_hex(path.relative_to(self._root).as_posix().encode("utf-8")),
            input_format="html",
        )

    def _tabular_records(
        self,
        path: Path,
        *,
        delimiter: str,
        remaining: int | None,
    ) -> Iterator[SourceRecord]:
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size > MAX_TABULAR_FILE_BYTES:
            logger.warning(
                "gwern.tabular_file_too_large path=%s size_bytes=%d",
                path,
                size,
            )
            return
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                return
            for row_number, row in enumerate(reader, start=2):
                if remaining is not None and row_number - 2 >= remaining:
                    break
                normalized = self._normalize_row(row)
                if not normalized:
                    continue
                source_bytes = canonical_json_bytes(normalized)
                yield self._record(
                    path,
                    source_bytes=source_bytes,
                    raw_content=json.dumps(
                        normalized,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    content_type=ContentType.JSON,
                    mime_type="application/json",
                    source_item_id=sha256_hex(
                        f"{path.relative_to(self._root).as_posix()}:{row_number}".encode()
                    ),
                    input_format="tsv" if delimiter == "\t" else "csv",
                    row_number=row_number,
                )

    @staticmethod
    def _normalize_row(row: Mapping[str | None, str | list[str] | None]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in row.items():
            if key is None or isinstance(value, list):
                continue
            clean_key = re.sub(r"[^a-z0-9_]+", "_", key.strip().casefold()).strip("_")
            clean_value = (value or "").strip()
            if clean_key and clean_value:
                normalized[clean_key[:100]] = clean_value
        return normalized

    def _record(
        self,
        path: Path,
        *,
        source_bytes: bytes,
        raw_content: str,
        content_type: ContentType,
        mime_type: str,
        source_item_id: str,
        input_format: str,
        row_number: int | None = None,
    ) -> SourceRecord:
        relative = path.relative_to(self._root)
        market = relative.parts[0] if len(relative.parts) > 1 else "unclassified"
        observed_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        encoded_path = quote(relative.as_posix(), safe="/-._")
        source_ref = f"dataset://gwern/{encoded_path}"
        if row_number is not None:
            source_ref = f"{source_ref}?row={row_number}"
        return SourceRecord(
            source_class=SourceClass.DNM_DATASET,
            source_ref=source_ref,
            content_type=content_type,
            mime_type=mime_type,
            raw_content=raw_content,
            source_bytes=source_bytes,
            captured_at=observed_at,
            source_observed_at=observed_at,
            crawl_metadata=CrawlMetadata(source_item_id=source_item_id),
            source_metadata={
                "dataset": DATASET_NAME,
                "dataset_reference": DATASET_REFERENCE,
                "input_format": input_format,
                "market": market,
            },
        )
