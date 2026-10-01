#!/usr/bin/env bash
# ── kb2-web 过期检测 · 人工触发（CLI） ──
# 自动过期已于 2026-10-01 停用（crontab 中原 04:00 作业已注释）。
# 本脚本是「人工触发」入口之一（另两个：管理页 LifecycleView 按钮 / GET /api/admin/stale/detect）。
#
# 用法：
#   ./stale_detect_manual.sh              # 默认 dry-run，只报告不写库（安全）
#   ./stale_detect_manual.sh --apply      # 真正把过期文档置为 stale（退出检索！）
#   ./stale_detect_manual.sh --apply --days 120
set -uo pipefail

cd /home/ubuntu/kb2-web/backend
export PYTHONPATH=/home/ubuntu/kb2-web/backend
PY=/home/ubuntu/.hermes/hermes-agent/venv/bin/python3

APPLY=0
DAYS=90
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --days) shift; DAYS="${1:-90}" ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done

if [ "$APPLY" = "1" ]; then
  DRY=false
  echo "⚠️  模式：APPLY —— 将真实把过期文档置为 stale（会退出检索）"
else
  DRY=true
  echo "模式：DRY-RUN —— 仅报告，不写库"
fi
echo "阈值：${DAYS} 天"
echo

"$PY" - "$DAYS" "$DRY" <<'PYEOF'
import sys
from app.models.database import SessionLocal
from app.services.stale_detection import detect_stale_documents, get_stale_summary

days = int(sys.argv[1])
dry = sys.argv[2].lower() == "true"

db = SessionLocal()
try:
    r = detect_stale_documents(db, max_days=days, dry_run=dry)
    if not dry:
        db.commit()
    s = get_stale_summary(db)
    print(f"检查 {r['total_checked']} 篇 / 命中过期 {r['stale_count']} 篇 "
          f"(dry_run={r['dry_run']}, max_days={r['max_days']})")
    for d in r["stale_docs"][:20]:
        print(f"  - {d['doc_id'][:8]}  {str(d.get('title'))[:34]}  [{d.get('bank')}]  {d.get('stale_reason')}")
    if len(r["stale_docs"]) > 20:
        print(f"  … 另有 {len(r['stale_docs']) - 20} 篇")
    print()
    print(f"当前 活跃={s['active']}  过期={s['stale']}  已替代={s['superseded']}  总计={s['total']}")
finally:
    db.close()
PYEOF
