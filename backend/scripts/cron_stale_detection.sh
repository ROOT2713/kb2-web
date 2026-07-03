#!/usr/bin/env bash
# ── Stale detection cron wrapper ──
# Invokes cron_stale_detection.py from the correct working directory.
#
# Install via crontab -e:
#   0 4 * * * /home/ubuntu/kb2-web/backend/scripts/cron_stale_detection.sh >> /home/ubuntu/kb2-web/logs/cron_stale.log 2>&1

set -euo pipefail

cd /home/ubuntu/kb2-web/backend
export PYTHONPATH=/home/ubuntu/kb2-web/backend

mkdir -p /home/ubuntu/kb2-web/logs

exec python3 scripts/cron_stale_detection.py
