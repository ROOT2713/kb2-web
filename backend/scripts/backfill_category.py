#!/usr/bin/env python3
"""Backfill missing category fields for existing documents."""
import sys, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.models.database import SessionLocal
from app.models.document import Document
from app.services.category_rules import infer_category, CATEGORIES

logger = logging.getLogger(__name__)

def backfill_categories(dry_run: bool = True):
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(
            (Document.category.is_(None)) | (Document.category == "")
        ).all()
        stats = {k: 0 for k in CATEGORIES}
        stats["unmatched"] = 0
        for doc in docs:
            cat = infer_category(title=doc.title or "", filename=doc.filename or "", bank=doc.bank or "")
            if cat and cat in CATEGORIES:
                stats[cat] += 1
                if not dry_run:
                    doc.category = cat
            else:
                stats["unmatched"] += 1
        if not dry_run:
            db.commit()
        total_assigned = sum(v for k, v in stats.items() if k != "unmatched")
        logger.info("=== Category Backfill %s ===", "DRY RUN" if dry_run else "EXECUTED")
        logger.info("Total empty docs: %d", len(docs))
        for k in sorted(stats):
            logger.info("  %s (%s): %d", k, CATEGORIES.get(k, ""), stats[k])
        logger.info("Assigned: %d, Unmatched: %d", total_assigned, stats["unmatched"])
        return stats
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--exec", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    dry_run = not args.exec
    backfill_categories(dry_run=dry_run)
