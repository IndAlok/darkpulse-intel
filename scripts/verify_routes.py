import sys

sys.path.insert(0, "src")

from darkpulse.api.app import app

for r in app.routes:
    path = getattr(r, "path", "")
    methods = getattr(r, "methods", None)
    if methods:
        print(f"{sorted(methods)[0]:6} {path}")
    elif path:
        print(f"WS     {path}")
