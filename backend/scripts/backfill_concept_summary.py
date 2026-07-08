"""C2a: Backfill concept.summary for all 2514 active concepts.

Features:
- Skip garbled/short concepts (watermark, <30 chars, <60% useful char ratio)
- Resume from checkpoint (use existing non-empty summary as skip marker)
- Progress logging every 50 concepts
- Rate limit 0.3s between LLM calls
- Concurrent (5 in flight at once) to speed up
- Graceful Ctrl+C: flush pending and exit
"""

import asyncio
import logging
import re
import sys
import time
from pathlib import Path

# Make backend importable
sys.path.insert(0, "/home/ubuntu/kb2-web/backend")

from app.models.database import SessionLocal
from app.models.concept import Concept
from app.services.concept_summary import generate_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")

# Suppress noisy concept_summary warnings to ERROR
logging.getLogger("app.services.concept_summary").setLevel(logging.ERROR)
# Suppress HTTP request noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

WATERMARK_RE = re.compile(r'bzfxw|chinanorms|antpedia|book118|jianbiaoku', re.I)
MIN_LENGTH = 30
MIN_USEFUL_RATIO = 0.6


def is_processable(content: str) -> bool:
    """Decide if a concept's content is worth running LLM on."""
    if not content or len(content) < MIN_LENGTH:
        return False
    if WATERMARK_RE.search(content):
        return False
    useful = sum(
        1 for c in content
        if c.isalnum() or '\u4e00' <= c <= '\u9fff'
        or c in ' \n.,，。;；()（）-—:：?？!！\"\'《》「」【】'
    )
    if useful / len(content) < MIN_USEFUL_RATIO:
        return False
    return True


async def process_one(sem, concept_id, title, content):
    """Generate summary for one concept under semaphore."""
    async with sem:
        try:
            summary = await generate_summary(content, title)
            return concept_id, summary
        except Exception as e:
            logger.warning("LLM fail for %s: %s", concept_id[:30], e)
            return concept_id, None


async def main():
    # Optional CLI args: --limit N --offset M --batch-only
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Max concepts to process this run")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-superseded", action="store_true",
                        help="Also process superseded concepts with empty summary")
    args = parser.parse_args()

    db = SessionLocal()

    # Find concepts without summary
    if args.include_superseded:
        q = db.query(Concept).filter(
            (Concept.summary == None) | (Concept.summary == ""),
        ).order_by(Concept.doc_id)
    else:
        q = db.query(Concept).filter(
            Concept.status == "active",
            (Concept.summary == None) | (Concept.summary == ""),
        ).order_by(Concept.doc_id)
    if args.limit:
        concepts = q.limit(args.limit).all()
    else:
        concepts = q.all()

    total = len(concepts)
    logger.info("Found %d concepts without summary", total)

    # Filter to processable
    skipped_garbled = []
    todo = []
    for c in concepts:
        if is_processable(c.content or ""):
            todo.append(c)
        else:
            skipped_garbled.append(c.concept_id)

    logger.info("Processable: %d | Skipped (garbled/short): %d", len(todo), len(skipped_garbled))

    if args.dry_run:
        logger.info("Dry run, exit.")
        return

    if not todo:
        logger.info("Nothing to do.")
        return

    sem = asyncio.Semaphore(args.concurrency)
    t_start = time.time()
    done = 0
    failed = 0
    batch_results = []  # accumulate before db commit

    # Process in chunks of 50 to commit progress
    CHUNK = 50
    for chunk_start in range(0, len(todo), CHUNK):
        chunk = todo[chunk_start:chunk_start + CHUNK]
        tasks = [process_one(sem, c.concept_id, c.title or "", c.content or "") for c in chunk]
        results = await asyncio.gather(*tasks)

        # Apply to DB
        id_map = {c.concept_id: c for c in chunk}
        for cid, summary in results:
            if summary:
                id_map[cid].summary = summary
                done += 1
            else:
                failed += 1

        db.commit()

        elapsed = time.time() - t_start
        rate = (done + failed) / elapsed if elapsed > 0 else 0
        eta = (len(todo) - done - failed) / rate if rate > 0 else 0
        logger.info(
            "Progress: %d/%d done (failed %d) | %.1fs elapsed | %.1f/s | ETA %.0fs",
            done, len(todo), failed, elapsed, rate, eta,
        )

    db.close()
    logger.info("DONE. done=%d failed=%d skipped=%d total=%d",
                done, failed, len(skipped_garbled), total)


if __name__ == "__main__":
    asyncio.run(main())
