#!/bin/sh
set -e

UPSTREAM=${BACKEND_UPSTREAM:-http://backend:8080}
PORT=${PORT:-5173}
RESOLVER=$(grep -m1 '^nameserver' /etc/resolv.conf 2>/dev/null | cut -d' ' -f2)
[ -n "$RESOLVER" ] || RESOLVER=127.0.0.11
case "$RESOLVER" in
  *:*) RESOLVER="[$RESOLVER]:53" ;;
esac

sed -e "s|__UPSTREAM__|$UPSTREAM|g" -e "s|__RESOLVER__|$RESOLVER|g" -e "s|__PORT__|$PORT|g" \
  /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

API_BASE=${DARKPULSE_API_URL:-}
case "$API_BASE" in
  ""|/*) ;;
  *) echo "DARKPULSE_API_URL must be empty or a same-origin path" >&2; exit 1 ;;
esac
case "$API_BASE" in
  *[\"\\\<\>\'\`]*) echo "DARKPULSE_API_URL contains a forbidden character" >&2; exit 1 ;;
esac

printf 'window.__DARKPULSE_CONFIG__ = {"apiBase": "%s"};\n' "$API_BASE" \
  > /usr/share/nginx/html/config.js

nginx -g "daemon off;"
