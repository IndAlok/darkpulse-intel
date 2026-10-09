"""Regenerate contracts/contract3-api.openapi.yaml from the live app.

Run after adding or changing any route. CI diffs this file against the app.

    python scripts/refresh_openapi.py
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts/contract3-api.openapi.yaml"

WS_ROUTE = {
    "get": {
        "tags": ["Alerts"],
        "summary": "AlertsWebsocket",
        "description": (
            "Live alert stream. Authenticate with a single-use ticket from "
            "POST /auth/ws-ticket passed as ?ticket=."
        ),
        "parameters": [
            {"name": "ticket", "in": "query", "required": True, "schema": {"type": "string"}},
        ],
        "responses": {"101": {"description": "Switching Protocols"}},
    }
}


def main() -> None:
    from darkpulse.api.app import app

    spec = app.openapi()
    spec["openapi"] = "3.1.0"
    spec["servers"] = [{"url": "http://localhost:8003"}]
    spec["paths"] = {path.removeprefix("/api/v1"): item for path, item in spec["paths"].items()}
    spec["paths"].setdefault("/alerts/ws", WS_ROUTE)
    CONTRACT.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    print(f"regenerated {CONTRACT} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
