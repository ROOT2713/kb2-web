#!/usr/bin/env python3
"""
Backfill metadata for vector_chunks that have incomplete metadata.
Root cause: register_vector corrupted JSONB codec during the code-base 
codec registration, so pgvector upserts stored empty {} for metadata fields
(title, category, bank, doc).

This script reads parent_chunks content from SQLite, joins with documents
table to get title/category/bank, and writes the enriched metadata back
to pgvector, one chunk at a time via a single UPDATE per chunk.

Pipeline:
  SQLite documents → SQLite parent_chunks → enrich metadata dict → psql UPDATE

Usage: python3 scripts/backfill_metadata.py
"""

import sqlite3
import json
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

KB_DB = os.environ.get("KB_DB", "/home/ubuntu/kb-web/data/kb.db")
PG_DSN = os.environ.get("PG_DSN", "postgresql://hindsight:hindsight123@localhost:5432/hindsight")

import asyncpg


async def backfill():
    conn = await asyncpg.connect(PG_DSN)
    db = sqlite3.connect(KB_DB)
    db.row_factory = sqlite3.Row

    try:
        # Step 1: Count how many chunks need fixing
        needs_meta = await conn.fetchval("""
            SELECT COUNT(*) FROM vector_chunks
            WHERE (metadata IS NULL
                   OR metadata::text = '{}'
                   OR metadata->>'title' IS NULL)
        """)
        logger.info("Chunks needing metadata backfill: %d", needs_meta)

        if needs_meta == 0:
            logger.info("No backfill needed — all metadata complete.")
            return

        # Step 2: Get distinct doc_ids that have incomplete metadata
        rows = await conn.fetch("""
            SELECT DISTINCT v.doc_id
            FROM vector_chunks v
            WHERE v.metadata IS NULL
               OR v.metadata::text = '{}'
               OR v.metadata->>'title' IS NULL
        """)
        doc_ids = [r["doc_id"] for r in rows]
        logger.info("Distinct doc_ids with incomplete metadata: %d", len(doc_ids))

        # Step 3: Batch query SQLite for title, category, bank
        placeholders = ",".join("?" for _ in doc_ids)
        doc_rows = db.execute(f"""
            SELECT doc_id, title, category, hs_bank, subcategory
            FROM documents
            WHERE doc_id IN ({placeholders})
        """, doc_ids).fetchall()

        doc_info = {}
        for r in doc_rows:
            doc_info[r["doc_id"]] = {
                "title": r["title"] or "",
                "category": r["category"] or "",
                "bank": r["hs_bank"] or "general",
                "subcategory": r["subcategory"] or "",
            }

        logger.info("Loaded %d document infos from SQLite", len(doc_info))

        # Step 4: For each doc_id, get the parent_idx→chunk mapping from parent_chunks
        # then update the corresponding vector_chunks rows
        updated = 0
        for doc_id in doc_ids:
            info = doc_info.get(doc_id, {})
            title = info.get("title", "")
            category = info.get("category", "")
            bank = info.get("bank", "general")

            # Build the metadata dict
            meta = {"title": title}
            if category:
                meta["category"] = category
            meta["bank"] = bank
            doc_filename = title  # filename is the title now
            if doc_filename:
                meta["doc"] = doc_filename

            meta_json = json.dumps(meta)

            # Update all vector_chunks for this doc_id
            result = await conn.execute("""
                UPDATE vector_chunks
                SET metadata = $1::jsonb
                WHERE doc_id = $2
                  AND (metadata IS NULL
                       OR metadata::text = '{}'
                       OR metadata->>'title' IS NULL)
            """, meta_json, doc_id)
            # result is like "UPDATE 42"
            count = int(result.split()[-1])
            updated += count

        logger.info("Updated %d vector_chunks with enriched metadata", updated)

        # Step 5: Verify
        remaining = await conn.fetchval("""
            SELECT COUNT(*) FROM vector_chunks
            WHERE metadata IS NULL
               OR metadata::text = '{}'
               OR metadata->>'title' IS NULL
        """)
        logger.info("Remaining incomplete metadata: %d", remaining)

    finally:
        await conn.close()
        db.close()

    return updated


if __name__ == "__main__":
    import asyncio
    n = asyncio.run(backfill())
    print(f"Done. Updated {n} vector_chunks with enriched metadata.")
