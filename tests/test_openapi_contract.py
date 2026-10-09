from pathlib import Path

import yaml

from darkpulse.api.app import app

CONTRACT = Path(__file__).resolve().parents[1] / "contracts/contract3-api.openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}


def _operations(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    return {(path, method) for path, item in paths.items() for method in item if method in METHODS}


def test_contract_lists_every_live_route_once() -> None:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    documented = _operations(spec["paths"])
    live = {
        (path.removeprefix("/api/v1"), method)
        for path, method in _operations(app.openapi()["paths"])
        if path.startswith("/api/v1")
    }
    live.add(("/alerts/ws", "get"))
    assert sorted(live - documented) == []
    assert sorted(documented - live) == []
