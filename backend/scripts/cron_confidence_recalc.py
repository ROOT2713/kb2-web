"""Confidence recalculation cron script.

Runs update_all_confidences() against all documents in the database.
Designed to be invoked from crontab.

Usage:
    cd /home/ubuntu/kb2-web/backend
    PYTHONPATH=. python3 scripts/cron_confidence_recalc.py

Or via the wrapper script: scripts/cron_confidence_recalc.sh
"""

import logging
import sys

# ── Bootstrap: ensure we can import app modules ──
# (PYTHONPATH must include backend/ directory)
try:
    from app.models.database import SessionLocal
    from app.services.confidence import update_all_confidences
except ImportError as e:
    print(f"FATAL: Cannot import app modules. Set PYTHONPATH to backend/ directory.\n{e}",
          file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cron_confidence_recalc")


def main():
    db = SessionLocal()
    try:
        logger.info("Starting confidence recalculation for all active concepts...")
        result = update_all_confidences(db)
        db.commit()
        logger.info(
            "Confidence recalc complete: total=%d, updated=%d, changed=%d",
            result["total"],
            result["updated"],
            result["changed"],
        )
    except Exception as e:
        db.rollback()
        logger.exception("Confidence recalculation failed: %s", e)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
