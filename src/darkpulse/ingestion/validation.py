from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from darkpulse.models import RawIngest


class ContractValidator:
    def __init__(self, schema_path: Path) -> None:
        schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )

    def validate(self, record: RawIngest) -> None:
        self._validator.validate(record.model_dump(mode="json"))
