from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    _standard_fields = frozenset(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._standard_fields and not key.startswith("_"):
                payload[key] = value
        if record.exc_info is not None:
            exc_type = record.exc_info[0]
            if exc_type is not None:
                payload["exception_type"] = exc_type.__name__
            payload["exception_traceback"] = "".join(
                traceback.format_exception(*record.exc_info)
            ).strip()
        return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
