"""Live end-to-end API probe against the running docker stack. Run: python scripts/e2e_probe.py"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from uuid import uuid4

BASE = "http://localhost:8003/api/v1"


def seal_header(hdrs: dict) -> str | None:
    for k, v in hdrs.items():
        if k.lower() == "x-darkpulse-evidence-seal":
            return v
    return None




def get_tokens() -> dict[str, dict[str, str]]:
    out = subprocess.run(
        ["docker", "exec", "darkpulse-backend-1", "printenv", "DARKPULSE_AUTH_TOKENS_JSON"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return json.loads(out)


def call(method, path, token=None, body=None, expect=None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as r:
            code, payload = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, payload = e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return ("EXC", str(e))
    ok = "OK" if (expect is None or code == expect) else "FAIL"
    return (code, ok, payload[:180].decode(errors="replace"))


def login(static_token: str) -> str:
    res = call("POST", "/auth/login", None, {"token": static_token}, 200)
    body = json.loads(res[2]) if res[0] == 200 else {}
    return body["data"]["token"]


def main() -> int:
    static = get_tokens()
    s_admin = next(k for k, v in static.items() if v["role"] == "administrator")
    s_analyst = next(k for k, v in static.items() if v["role"] == "analyst")
    s_viewer = next(k for k, v in static.items() if v["role"] == "viewer")
    admin, analyst, viewer = login(s_admin), login(s_analyst), login(s_viewer)

    results = [
        ("health", call("GET", "/health")),
        ("login-bad", call("POST", "/auth/login", None, {"token": "x" * 40}, 401)),
        ("intel-unauth", call("GET", "/intel", None, None, 401)),
        ("me-analyst", call("GET", "/auth/me", analyst, None, 200)),
    ]
    for name, tok in [("analyst", analyst), ("viewer", viewer)]:
        for route in [
            "/intel?limit=5", "/search?q=charas", "/actors", "/graph",
            "/dashboards/trends", "/dashboards/sources", "/dashboards/geo",
            "/alerts/history", "/watchlists", "/slang", "/slang/candidates",
            "/evidence/verify",
        ]:
            label = route.split("?")[0][1:].replace("/", "-")
            results.append((f"{label}-{name}", call("GET", route, tok, None, 200)))
    results += [
        ("viewer-slang-denied", call(
            "POST", "/slang", viewer, {"term": "zz", "meaning": "t", "lang": "en"}, 403
        )),
        ("analyst-slang-create", call(
            "POST", "/slang", analyst,
            {"term": f"probe-{uuid4().hex[:8]}", "meaning": "probe entry", "lang": "en"}, 201,
        )),
        ("dash-bad-period", call("GET", "/dashboards/trends?period=1y", analyst, None, 422)),
        ("intel-limit-0", call("GET", "/intel?limit=0", analyst, None, 422)),
        ("intel-limit-999", call("GET", "/intel?limit=999", analyst, None, 422)),
        ("ops-viewer", call("GET", "/operations/sources", viewer, None, 403)),
        ("ops-analyst", call("GET", "/operations/sources", analyst, None, 403)),
        ("ops-admin", call("GET", "/operations/sources", admin, None, 200)),
        ("ops-processing-admin", call("GET", "/operations/processing", admin, None, 200)),
        ("ops-audit-admin", call("GET", "/operations/audit", admin, None, 200)),
        ("ops-runs-admin", call("GET", "/operations/collection-runs", admin, None, 200)),
        ("export-noauth", call("POST", "/export?format=csv", None, None, 401)),
        ("404-envelope", call("GET", "/nonexistent", analyst, None, 404)),
        ("405-envelope", call("DELETE", "/intel", analyst, None, 405)),
    ]

    print(f"{'CHECK':36} {'CODE':>5}  RES    DETAIL")
    fails = 0
    for name, res in results:
        code, ok = res[0], res[1]
        detail = res[2] if len(res) > 2 else ""
        if ok == "FAIL":
            fails += 1
        print(f"{name:36} {str(code):>5}  {ok:4}  {detail[:70]}{'  <<<<' if ok == 'FAIL' else ''}")
    print(f"\n{fails} failures / {len(results)} checks")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
