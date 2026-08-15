#!/bin/sh
set -e
exec python -m darkpulse.cli collect-all --loop --interval "${COLLECT_INTERVAL:-300}"
