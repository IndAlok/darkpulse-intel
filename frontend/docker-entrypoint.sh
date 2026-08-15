#!/bin/sh
set -e

UPSTREAM=${BACKEND_UPSTREAM:-http://backend:8080}
RESOLVER=$(grep -m1 '^nameserver' /etc/resolv.conf 2>/dev/null | cut -d' ' -f2)
[ -n "$RESOLVER" ] || RESOLVER=10.0.0.2
case "$RESOLVER" in
  *:*) RESOLVER="[$RESOLVER]:53" ;;
esac

sed -e "s|__UPSTREAM__|$UPSTREAM|g" -e "s|__RESOLVER__|$RESOLVER|g" \
  /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

cat > /usr/share/nginx/html/config.js <<EOF
window.__DARKPULSE_CONFIG__ = {
  apiBase: "${DARKPULSE_API_URL:-}",
};
EOF

nginx -g "daemon off;"
