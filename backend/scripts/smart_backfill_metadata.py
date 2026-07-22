#!/usr/bin/env python3
"""
Smart metadata backfill for vector_chunks.

Strategy: Only backfill for doc_ids that exist in both pgvector AND SQLite
(documents table). For these, we have complete metadata (title, category, bank).
Skip orphaned pgvector doc_ids (no corresponding SQLite record).

This prevents setting '{"bank": "general", "title": ""}' for orphans.
"""

import sqlite3, json, logging, asyncio, asyncpg, os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smart-backfill")

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"


async def backfill():
    conn = await asyncpg.connect(PG_DSN)
    db = sqlite3.connect(KB_DB)
    db.row_factory = sqlite3.Row

    try:
        # 1. Get all pgvector doc_ids
        pg_rows = await conn.fetch("""
            SELECT DISTINCT doc_id::text
            FROM vector_chunks
        """)
        pg_doc_ids = set(r["doc_id"] for r in pg_rows)
        logger.info("pgvector doc_ids with incomplete metadata: %d", len(pg_doc_ids))

        # 2. Get SQLite doc_ids
        sqlite_rows = db.execute("SELECT doc_id, title, category, hs_bank, subcategory FROM documents").fetchall()
        sqlite_doc_ids = set(r["doc_id"] for r in sqlite_rows)
        logger.info("SQLite documents: %d", len(sqlite_doc_ids))

        # 3. Only match overlapping doc_ids
        overlap = pg_doc_ids & sqlite_doc_ids
        orphans = pg_doc_ids - sqlite_doc_ids
        logger.info("Overlap (can backfill): %d", len(overlap))
        logger.info("Orphans (will skip): %d", len(orphans))

        if overlap:
            doc_info = {r["doc_id"]: dict(r) for r in sqlite_rows if r["doc_id"] in overlap}
            logger.info("Loaded %d document infos", len(doc_info))

            updated = 0
            for doc_id in overlap:
                info = doc_info.get(doc_id, {})
                meta = {
                    "title": info.get("title", "") or "",
                    "category": info.get("category", "") or "",
                    "bank": info.get("hs_bank", "general") or "general",
                }
                meta_json = json.dumps(meta)
                # For orphans from the backfill script that have {"bank":"general","title":""},
                # the title is empty - only update if we can actually fill it
                r = await conn.execute("""
                    UPDATE vector_chunks
                    SET metadata = $1::jsonb
                    WHERE doc_id = $2
                """, meta_json, doc_id)
                updated += int(r.split()[-1]) if r else 0

            logger.info("Updated total %d vector_chunks", updated)

        # 4. Verify
        remaining = await conn.fetchval("""
            SELECT COUNT(*) FROM vector_chunks
            WHERE metadata->>'title' IS NULL
               OR metadata->>'title' = ''
        """)
        logger.info("Remaining with empty title: %d", remaining)

    finally:
        await conn.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(backfill())
    print("Done.")
