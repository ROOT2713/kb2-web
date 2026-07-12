#!/usr/bin/env bash
# kb2-web Health Check (MVP)
# Usage: ./health_check.sh [--restart]
set -euo pipefail

NAME="kb2-web"
URL="http://localhost:3027/login"
FAIL=0

# ── Check 1: Process alive ──
if systemctl is-active --quiet kb2-web 2>/dev/null; then
  echo "✓ systemd: kb2-web active"
else
  echo "✗ systemd: kb2-web NOT active"
  FAIL=1
fi

# ── Check 2: HTTP 200 ──
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  echo "✓ HTTP: $URL → $HTTP_CODE"
else
  echo "✗ HTTP: $URL → $HTTP_CODE"
  FAIL=1
fi

# ── Check 3: API /api/banks ──
API_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3027/api/banks" 2>/dev/null || echo "000")
if [ "$API_CODE" = "401" ] || [ "$API_CODE" = "200" ]; then
  echo "✓ API: /api/banks → $API_CODE (expected: 401=no-auth or 200=auth)"
else
  echo "✗ API: /api/banks → $API_CODE"
  FAIL=1
fi

# ── Result ──
if [ "$FAIL" -eq 1 ]; then
  echo "FAIL: ${NAME} health check failed"
  if [ "${1:-}" = "--restart" ]; then
    echo "→ restarting ${NAME}..."
    sudo systemctl restart kb2-web
    sleep 5
    echo "→ rechecking..."
    exec "$0"  # re-run without --restart
  fi
  exit 1
fi

echo "OK: $NAME is healthy"
exit 0
