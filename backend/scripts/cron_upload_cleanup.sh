#!/usr/bin/env bash
# ── Upload task cleanup cron wrapper ──
# Invokes cron_upload_cleanup.py from the correct working directory.
#
# Install via crontab -e:
#   0 5 * * * /home/ubuntu/kb2-web/backend/scripts/cron_upload_cleanup.sh >> /home/ubuntu/kb2-web/logs/cron_upload_cleanup.log 2>&1

set -euo pipefail

cd /home/ubuntu/kb2-web/backend
export PYTHONPATH=/home/ubuntu/kb2-web/backend

mkdir -p /home/ubuntu/kb2-web/logs

exec python3 scripts/cron_upload_cleanup.py
