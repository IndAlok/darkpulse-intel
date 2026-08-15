import json

import pytest
from pydantic import ValidationError

from darkpulse.ingestion.collectors.registry import SourceDefinition, SourceRegistry
from darkpulse.models import SourceClass


def make_source(source_id: str, *, enabled: bool = True) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        source_class=SourceClass.SURFACE_MARKET,
        enabled=enabled,
        locator="https://example.invalid/approved",
    )


def test_registry_rejects_duplicate_and_unknown_sources() -> None:
    source = make_source("source-a")

    with pytest.raises(ValueError, match="duplicate"):
        SourceRegistry([source, source])

    registry = SourceRegistry([source])
    with pytest.raises(KeyError, match="unknown source_id"):
        registry.get("missing")


def test_registry_returns_enabled_sources_in_stable_order() -> None:
    registry = SourceRegistry(
        [make_source("source-b"), make_source("source-a"), make_source("source-c", enabled=False)]
    )

    assert [source.source_id for source in registry.enabled()] == ["source-a", "source-b"]
    assert registry.enabled(source_class=SourceClass.TELEGRAM) == ()


def test_registry_loads_strict_json(tmp_path) -> None:
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            [
                {
                    "source_id": "source-a",
                    "source_class": "paste",
                    "enabled": False,
                    "locator": "https://example.invalid/paste",
                }
            ]
        ),
        encoding="utf-8",
    )

    registry = SourceRegistry.from_path(path)

    assert registry.get("source-a").source_class is SourceClass.PASTE


def test_source_definition_rejects_unstable_id_and_oversized_limit() -> None:
    with pytest.raises(ValidationError):
        make_source("Source With Spaces")
    with pytest.raises(ValidationError):
        SourceDefinition(
            source_id="source-a",
            source_class=SourceClass.PASTE,
            locator="https://example.invalid",
            max_response_bytes=2_000_001,
        )
