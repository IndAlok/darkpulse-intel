from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from darkpulse.models import SourceClass

SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,199}$")


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_class: SourceClass
    enabled: bool = False
    locator: str = Field(min_length=1, max_length=2048)
    max_response_bytes: int = Field(default=2_000_000, ge=1, le=2_000_000)
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_retries: int = Field(default=3, ge=0, le=8)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        if not SOURCE_ID_PATTERN.fullmatch(value):
            raise ValueError("source_id must be a lowercase stable identifier")
        return value


class SourceRegistry:
    def __init__(self, sources: list[SourceDefinition]) -> None:
        by_id = {source.source_id: source for source in sources}
        if len(by_id) != len(sources):
            raise ValueError("source registry contains duplicate source IDs")
        self._sources = by_id

    @classmethod
    def from_path(cls, path: Path) -> SourceRegistry:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("source registry must be a JSON array")
        return cls([SourceDefinition.model_validate(item) for item in payload])

    def get(self, source_id: str) -> SourceDefinition:
        try:
            return self._sources[source_id]
        except KeyError as error:
            raise KeyError(f"unknown source_id: {source_id}") from error

    @property
    def sources(self) -> tuple[SourceDefinition, ...]:
        return tuple(sorted(self._sources.values(), key=lambda source: source.source_id))

    def enabled(self, *, source_class: SourceClass | None = None) -> tuple[SourceDefinition, ...]:
        sources = (
            source
            for source in self._sources.values()
            if source.enabled and (source_class is None or source.source_class is source_class)
        )
        return tuple(sorted(sources, key=lambda source: source.source_id))
