"""Deep live flow probe: export seal, manifest, watchlists, slang, alerts, tickets."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = "http://localhost:8003/api/v1"


def seal_header(hdrs: dict) -> str | None:
    for k, v in hdrs.items():
        if k.lower() == "x-darkpulse-evidence-seal":
            return v
    return None




def get_static_tokens() -> Any:
    out = subprocess.run(
        ["docker", "exec", "darkpulse-backend-1", "printenv", "DARKPULSE_AUTH_TOKENS_JSON"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return json.loads(out)


def call(
    method: str, path: str, token: str | None = None, body: Any = None, raw: bool = False
) -> Any:
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            code, payload, hdrs = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        code, payload, hdrs = e.code, e.read(), dict(e.headers)
    except Exception as exc:  # noqa: BLE001
        return (503, {"errors": [{"message": str(exc)}]}, {})
    if raw:
        return code, payload, hdrs
    try:
        parsed: Any = json.loads(payload)
    except Exception:  # noqa: BLE001
        return code, payload[:200].decode(errors="replace"), hdrs
    return code, parsed, hdrs


def login(static: str) -> str:
    _, body, _ = call("POST", "/auth/login", None, {"token": static})
    return str(body["data"]["token"])


def main() -> int:
    static = get_static_tokens()
    s_admin = next(k for k, v in static.items() if v["role"] == "administrator")
    s_analyst = next(k for k, v in static.items() if v["role"] == "analyst")
    admin, analyst = login(s_admin), login(s_analyst)
    checks: list[tuple[str, object, object]] = []

    c, b, _ = call("GET", "/intel?limit=3", analyst)
    ids = [r["intel_id"] for r in b["data"]]
    checks.append(("intel-list", c == 200 and len(ids) > 0, ids[:2]))

    c, payload, hdrs = call("POST", f"/export?format=csv&intel_ids={ids[0]}", analyst, raw=True)
    seal = seal_header(hdrs)
    checks.append(("export-post-csv", c == 200 and bool(seal), seal))

    c, b, _ = call("GET", f"/export/manifest/{seal}", analyst)
    ok = c == 200 and b["data"]["intel_ids"] == [ids[0]]
    checks.append(("manifest-by-hash", ok, b["data"].get("intel_ids") if c == 200 else b))

    _, _, h2 = call("POST", f"/export?format=csv&intel_ids={ids[0]}", analyst, raw=True)
    checks.append(("export-idempotent", seal_header(h2) == seal, ""))

    _, b, _ = call("GET", "/evidence/verify", analyst)
    before = b["data"]["record_count"]
    call("POST", f"/export?format=csv&intel_ids={ids[0]}", analyst)
    _, b, _ = call("GET", "/evidence/verify", analyst)
    after = b["data"]["record_count"]
    checks.append(("ledger-no-dup", after == before, f"{before}->{after}"))

    _, b, _ = call("GET", "/evidence/verify", analyst)
    checks.append(("chain-verified", b["data"]["verified"] is True, b["data"]))

    c, b, _ = call(
        "POST", "/watchlists", analyst, {"name": "e2e-probe-list", "terms": ["charas", "snow"]}
    )
    wl_id = b["data"]["id"] if c == 201 else None
    checks.append(("watchlist-create", c == 201 and bool(wl_id), wl_id))
    c, b, _ = call("PUT", f"/watchlists/{wl_id}", analyst, {"notify": False})
    checks.append(("watchlist-notify-toggle", c == 200 and b["data"]["notify"] is False, ""))
    c, _, _ = call("DELETE", f"/watchlists/{wl_id}", analyst)
    checks.append(("watchlist-delete", c == 204, c))

    c, b, _ = call("GET", "/alerts/config", analyst)
    rules = b["data"]["rules"]
    c, b, _ = call("PUT", "/alerts/config", analyst, {"rules": rules})
    checks.append(("alert-config-roundtrip", c == 200, f"{len(rules)} rules"))

    c, b, _ = call(
        "POST", "/slang", analyst,
        {"term": "zzpending", "meaning": "probe pending", "lang": "en", "newly_discovered": True},
    )
    sid = b["data"]["id"] if c == 201 else None
    c, _, _ = call("POST", f"/slang/{sid}/approve", analyst)
    checks.append(("slang-approve", c == 200, c))
    c, _, _ = call("DELETE", f"/slang/{sid}", analyst)
    checks.append(("slang-cleanup", c == 204, c))

    c, b, _ = call("POST", "/alerts/ws-ticket", analyst)
    checks.append(("ws-ticket", c == 200 and "ticket" in json.dumps(b), c))

    c, _, _ = call("POST", "/operations/dead-letter/nonexistent-id/retry", admin)
    checks.append(("dead-letter-unknown-404", c == 404, c))

    fails = 0
    print(f"{'CHECK':26} RESULT  DETAIL")
    for name, ok, detail in checks:
        good = ok is True
        if not good:
            fails += 1
        print(f"{name:26} {'OK' if good else str(ok):6}  {str(detail)[:90]}")
    print(f"\n{fails} failures / {len(checks)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
