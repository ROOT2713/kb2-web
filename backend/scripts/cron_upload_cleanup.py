"""Upload task cleanup cron script.

Deletes completed or failed upload tasks older than 30 days.
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


def main():
    db = SessionLocal()
    try:
        logger.info("Starting upload task cleanup (max_age_days=30)...")
        deleted = UploadTask.cleanup_old_tasks(db, max_age_days=30)
        logger.info("Upload task cleanup complete: deleted=%d", deleted)
    except Exception as e:
        db.rollback()
        logger.exception("Upload task cleanup failed: %s", e)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
