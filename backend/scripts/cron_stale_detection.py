"""Stale detection cron script.

Runs stale detection on all active documents once, then logs results.

Usage:
    cd /home/ubuntu/kb2-web/backend
    PYTHONPATH=. python3 scripts/cron_stale_detection.py

Or via the wrapper script: scripts/cron_stale_detection.sh
"""

import logging
import sys

try:
    from app.models.database import SessionLocal
    from app.services.stale_detection import detect_stale_documents
except ImportError as e:
    print(f"FATAL: Cannot import app modules. Set PYTHONPATH to backend/ directory.\n{e}",
          file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cron_stale_detection")


def main():
    db = SessionLocal()
    try:
        logger.info("Starting stale detection for all active documents...")
        result = detect_stale_documents(db, dry_run=False)
        db.commit()

        stale_count = result.get("stale_count", 0)
        total_checked = result.get("total_checked", 0)
        stale_docs = result.get("stale_docs", [])

        logger.info(
            "Stale detection complete: checked=%d, stale=%d",
            total_checked,
            stale_count,
        )
        if stale_docs:
            for d in stale_docs:
                logger.info(
                    "  STALE: id=%s title=%s bank=%s reason=%s",
                    d.get("doc_id", "?")[:8],
                    d.get("title", "?"),
                    d.get("bank", "?"),
                    d.get("stale_reason", "?"),
                )
    except Exception as e:
        logger.exception("Stale detection failed: %s", e)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
