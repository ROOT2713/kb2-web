#!/usr/bin/env bash
# ── Confidence recalculation cron wrapper ──
# Invokes cron_confidence_recalc.py from the correct working directory.
#
# Install via crontab -e:
#   0 3 * * * /home/ubuntu/kb2-web/backend/scripts/cron_confidence_recalc.sh >> /home/ubuntu/kb2-web/logs/cron_confidence.log 2>&1

set -euo pipefail

cd /home/ubuntu/kb2-web/backend
export PYTHONPATH=/home/ubuntu/kb2-web/backend

mkdir -p /home/ubuntu/kb2-web/logs

exec python3 scripts/cron_confidence_recalc.py
