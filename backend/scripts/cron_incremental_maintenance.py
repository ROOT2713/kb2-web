#!/usr/bin/env python3
"""C4: Incremental maintenance cron — G2 concept/summary backfill + G3 crystallization.

Runs periodically to:
  1. G2:  Find searchable docs without concepts → generate concepts + KG + summaries
  2. G2b: Find concepts without summaries → backfill via LLM
  3. G3:  Run crystallization (incremental — skips already-judged pairs)

Usage:
  python backend/scripts/cron_incremental_maintenance.py [--dry-run]

Exit codes:
  0 = success (or nothing to do)
  1 = error
"""

import sys
import os
import asyncio
import logging
import time
import importlib.util
from datetime import datetime, timezone

# ── Path setup ──
_BACKEND = "/home/ubuntu/kb2-web/backend"
sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

# Load .env (LLM_API_KEY, embedding config, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BACKEND, ".env"))
except ImportError:
    pass  # .env may already be in env

from sqlalchemy import text as sa_text
from app.models.database import SessionLocal

# Lazy imports for heavy modules (only when needed)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cron_maintenance")


def _load_kg_client():
    """Load kg_client.py dynamically (not a proper package)."""
    spec = importlib.util.spec_from_file_location(
        "kg_client", os.path.join(_BACKEND, "scripts", "kg_client.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.kg_index_document


def phase_1_backfill_concepts(db, dry_run: bool = False) -> dict:
    """G2: Find searchable docs without concepts → generate concepts + KG + summaries.

    These are newly uploaded docs that haven't been through the concept pipeline.
    Mirrors rebuild_concepts.py logic.
    """
    from app.services.concept_gen import (
        generate_concepts_for_doc,
        infer_doc_concept_id,
        infer_domain,
    )
    from app.services.concept_summary import generate_summaries_batch
    kg_index_document = _load_kg_client()

    # Find searchable docs with zero concepts
    rows = db.execute(
        sa_text("""
            SELECT d.doc_id, d.title, d.bank, d.doc_type
            FROM documents d
            WHERE d.searchable = 1
              AND NOT EXISTS (
                  SELECT 1 FROM concepts c WHERE c.doc_id = d.doc_id
              )
            ORDER BY d.created_at DESC
            LIMIT 20
        """)
    ).fetchall()

    if not rows:
        logger.info("[G2] No docs without concepts — skipping")
        return {"scanned": 0, "processed": 0, "failed": 0}

    logger.info("[G2] Found %d docs without concepts", len(rows))

    if dry_run:
        for doc_id, doc_title, _, _ in rows:
            logger.info("[G2] DRY-RUN: would process %s — '%s'", doc_id[:8], (doc_title or "")[:50])
        return {"scanned": len(rows), "processed": 0, "failed": 0}

    processed = 0
    failed = 0

    for doc_id, doc_title, bank, doc_type in rows:
        doc_id = str(doc_id)
        try:
            # 1) Load parent_chunks
            chunks = db.execute(
                sa_text(
                    "SELECT parent_idx, parent_text FROM parent_chunks "
                    "WHERE doc_id=:did ORDER BY parent_idx"
                ),
                {"did": doc_id},
            ).fetchall()
            if not chunks:
                logger.warning("[G2] %s: no parent_chunks, skipping", doc_id[:8])
                failed += 1
                continue

            parent_map = [{"parent_index": idx, "parent": text} for idx, text in chunks]
            full_text = "\n\n".join(text for _, text in chunks)
            logger.info(
                "[G2] %s: %d chunks, %d chars — '%s'",
                doc_id[:8], len(parent_map), len(full_text), (doc_title or "")[:50],
            )

            # 2) Update doc metadata
            _doc_type = doc_type or "generic"
            doc_concept_id = infer_doc_concept_id(
                title=doc_title, bank=bank, doc_type=_doc_type, text=full_text[:2000]
            )
            domain = infer_domain(bank, _doc_type)
            db.execute(
                sa_text(
                    "UPDATE documents SET doc_type=:dt, concept_id=:cid, "
                    "domain=:domain, chunk_count=:cc, coverage_pct=100.0 "
                    "WHERE doc_id=:did"
                ),
                {
                    "dt": _doc_type, "cid": doc_concept_id, "domain": domain,
                    "cc": len(parent_map), "did": doc_id,
                },
            )
            db.commit()

            # 3) Generate concepts (concept_gen uses flush() — we commit after)
            concept_count = generate_concepts_for_doc(
                db, doc_id, doc_concept_id, parent_map,
                doc_type=_doc_type, confidence=0.85,
            )
            db.commit()
            logger.info("[G2] %s: %d concepts generated", doc_id[:8], concept_count)

            # 4) KG triples (non-critical)
            try:
                kg_result = kg_index_document(doc_id, doc_title, full_text, bank)
                logger.info(
                    "[G2] %s: KG triples=%s", doc_id[:8], kg_result.get("count", 0)
                )
            except Exception as e:
                logger.warning("[G2] %s: KG triple gen failed (non-critical): %s", doc_id[:8], e)

            # 5) Backfill summaries
            if concept_count > 0:
                summary_count = asyncio.run(
                    generate_summaries_batch(db, doc_id, limit=100)
                )
                db.commit()
                logger.info("[G2] %s: %d summaries generated", doc_id[:8], summary_count)

            processed += 1

        except Exception as e:
            logger.error("[G2] %s: FAILED — %s", doc_id[:8], e, exc_info=True)
            db.rollback()
            failed += 1

    return {"scanned": len(rows), "processed": processed, "failed": failed}


def phase_2_backfill_summaries(db, dry_run: bool = False) -> dict:
    """G2b: Find concepts without summaries → backfill via LLM.

    Handles docs that have concepts but summaries failed in phase 1
    (e.g., LLM timeout, partial failure).
    """
    from app.services.concept_summary import generate_summaries_batch

    # Find docs with concepts that have empty summaries
    rows = db.execute(
        sa_text("""
            SELECT c.doc_id, COUNT(*) as missing
            FROM concepts c
            WHERE c.status = 'active'
              AND (c.summary IS NULL OR c.summary = '')
            GROUP BY c.doc_id
            LIMIT 20
        """)
    ).fetchall()

    if not rows:
        logger.info("[G2b] No concepts missing summaries — skipping")
        return {"scanned": 0, "processed": 0, "failed": 0}

    logger.info("[G2b] Found %d docs with missing summaries", len(rows))

    if dry_run:
        for doc_id, missing_count in rows:
            logger.info("[G2b] DRY-RUN: would backfill %d summaries for %s", missing_count, doc_id[:8])
        return {"scanned": len(rows), "processed": 0, "failed": 0}

    processed = 0
    failed = 0

    for doc_id, missing_count in rows:
        doc_id = str(doc_id)
        try:
            logger.info("[G2b] %s: %d summaries missing", doc_id[:8], missing_count)
            count = asyncio.run(generate_summaries_batch(db, doc_id, limit=100))
            db.commit()
            logger.info("[G2b] %s: %d summaries backfilled", doc_id[:8], count)
            processed += 1
        except Exception as e:
            logger.error("[G2b] %s: FAILED — %s", doc_id[:8], e, exc_info=True)
            db.rollback()
            failed += 1

    return {"scanned": len(rows), "processed": processed, "failed": failed}


def phase_3_crystallization(db) -> dict:
    """G3: Run incremental crystallization (LLM contradiction judgment).

    collect_grey_zone_candidates already skips pairs that have been judged
    (concept_contradictions.llm_verdict IS NOT NULL), so this is inherently
    incremental — only new docs' new concepts produce new grey-zone pairs.
    """
    from app.services.crystallization_light import run_crystallization

    logger.info("[G3] Starting incremental crystallization...")
    result = run_crystallization(db, limit=500, batch_size=8)
    logger.info(
        "[G3] Crystallization done: candidates=%d, judged=%d, verdicts=%s",
        result.get("candidates", 0),
        result.get("judged", 0),
        result.get("verdicts", {}),
    )
    return result


def main():
    dry_run = "--dry-run" in sys.argv
    start = time.time()
    logger.info("=" * 60)
    logger.info("C4 Incremental Maintenance — %s", datetime.now().isoformat())
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN — scanning only, no changes")

    db = SessionLocal()
    try:
        # G2: concept backfill for new docs
        r1 = phase_1_backfill_concepts(db, dry_run=dry_run)

        # G2b: summary backfill for partial failures
        r2 = phase_2_backfill_summaries(db, dry_run=dry_run)

        # G3: crystallization (incremental)
        if not dry_run:
            r3 = phase_3_crystallization(db)
        else:
            r3 = {"skipped": "dry-run"}
            logger.info("[G3] Skipped (dry-run)")

    except Exception as e:
        logger.error("Cron failed: %s", e, exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(
        "C4 DONE in %.1fs — G2:%s G2b:%s G3:%s",
        elapsed,
        r1.get("processed", 0),
        r2.get("processed", 0),
        r3.get("judged", 0),
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
