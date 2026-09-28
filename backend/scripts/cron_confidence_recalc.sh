#!/usr/bin/env bash
# ── Confidence recalculation cron wrapper ──
# Invokes cron_confidence_recalc.py with the project venv interpreter.
#
# Install via crontab -e:
#   0 3 * * * /home/ubuntu/kb2-web/backend/scripts/cron_confidence_recalc.sh >> /home/ubuntu/kb2-web/logs/cron_confidence.log 2>&1
#
# 2026-09-28 修复：原实现用裸 `python3` —— cron 的最小 PATH 解析到
#   /usr/bin/python3 (3.12，无 sqlalchemy)，导致每日 FATAL
#   「Cannot import app modules」,治理任务连续失效。
#   改用 venv 绝对路径；并加 START/OK/FAIL 心跳，防止再次静默失效。

set -uo pipefail

cd /home/ubuntu/kb2-web/backend
export PYTHONPATH=/home/ubuntu/kb2-web/backend

PY=/home/ubuntu/.hermes/hermes-agent/venv/bin/python3
JOB=cron_confidence_recalc
mkdir -p /home/ubuntu/kb2-web/logs

hb() { printf '[%s] [HEARTBEAT] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

if [ ! -x "$PY" ]; then
  hb "FAIL $JOB interpreter missing: $PY"
  exit 127
fi

hb "START $JOB interp=$PY"
rc=0
"$PY" scripts/cron_confidence_recalc.py || rc=$?
if [ "$rc" -eq 0 ]; then
  hb "OK $JOB rc=0"
else
  hb "FAIL $JOB rc=$rc"
fi
exit "$rc"
