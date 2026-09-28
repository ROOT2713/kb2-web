"""Upload task cleanup cron script.

Two-stage cleanup of the upload_tasks table:

1. **非终态滞留**（2026-09-29 新增）：把超过 24h 仍停在 pending/processing
   的任务标记为 failed。原实现只做第 2 步，导致非终态行**永久滞留**
   （worker 崩溃 / 服务被杀 / 入队后从未被取走），/tasks 轮询永远显示
   "进行中"。实证：18 行自 2026-09-18 08:28 滞留 11 天。
2. **终态超期**：删除 done/failed 且超过 30 天的行。

Designed to be invoked from crontab.

Usage:
    cd /home/ubuntu/kb2-web/backend
    PYTHONPATH=. python3 scripts/cron_upload_cleanup.py

Or via the wrapper script: scripts/cron_upload_cleanup.sh
"""

import logging
import sys

try:
    from app.models.database import SessionLocal
    from app.models.upload_task import UploadTask
except ImportError as e:
    print(f"FATAL: Cannot import app modules. Set PYTHONPATH to backend/ directory.\n{e}",
          file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cron_upload_cleanup")

# 非终态（pending/processing）滞留多久判死。远大于任何真实解析耗时。
INFLIGHT_MAX_HOURS = 24


def main():
    db = SessionLocal()
    try:
        logger.info("Starting upload task cleanup (terminal>%dd, inflight>%dh)...",
                    30, INFLIGHT_MAX_HOURS)
        # ① 先处理非终态滞留（2026-09-29 修复的盲区）——必须在删终态之前，
        #    因为标记 failed 会让这些行变成「刚更新」，不会误入本次删除。
        stale = UploadTask.cleanup_stale_inflight(db, max_age_hours=INFLIGHT_MAX_HOURS)
        # ② 再删已终结且超期的行
        deleted = UploadTask.cleanup_old_tasks(db, max_age_days=30)
        logger.info("Upload task cleanup complete: inflight_marked_failed=%d, "
                    "terminal_deleted=%d", stale, deleted)
    except Exception as e:
        db.rollback()
        logger.exception("Upload task cleanup failed: %s", e)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
