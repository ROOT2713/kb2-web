#!/usr/bin/env python3
"""
Deduplicate vector_chunks — remove duplicate (doc_id, chunk_index) rows,
keeping only the row with the longest metadata (most complete fields).
Also add UNIQUE constraint to prevent future duplicates.

Root cause: fix_searchable_zero.py INSERTed rows without DELETE-first,
creating up to 66 copies of the same chunk with varying metadata lengths.
When the query pipeline picks a row, it may get the short-metadata variant,
resulting in empty title/category/content in search results.
"""

import asyncio
import asyncpg
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dedup")

DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"


async def dedup():
    conn = await asyncpg.connect(DSN)
    try:
        # 1. Count duplicates
        before = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks")
        dup_groups = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT doc_id, chunk_index
                FROM vector_chunks
                GROUP BY doc_id, chunk_index
                HAVING COUNT(*) > 1
            ) d
        """)
        logger.info("Before: %d rows, %d duplicate groups", before, dup_groups)

        # 2. For each duplicate group, keep the row with longest (most complete) metadata
        # Use a CTE: row_number() within each (doc_id, chunk_index), order by LENGTH(metadata::text) DESC
        deleted = await conn.execute("""
            WITH ranked AS (
                SELECT ctid,
                       ROW_NUMBER() OVER (
                           PARTITION BY doc_id, chunk_index
                           ORDER BY LENGTH(metadata::text) DESC, LENGTH(content) DESC
                       ) AS rn
                FROM vector_chunks
            )
            DELETE FROM vector_chunks
            WHERE ctid IN (
                SELECT ctid FROM ranked WHERE rn > 1
            )
        """)
        after = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks")
        removed = before - after
        logger.info("After: %d rows, removed %d duplicates", after, removed)

        # 3. Add UNIQUE constraint to prevent future duplicates
        try:
            await conn.execute("""
                ALTER TABLE vector_chunks
                ADD CONSTRAINT vector_chunks_doc_id_chunk_index_key
                UNIQUE (doc_id, chunk_index)
            """)
            logger.info("UNIQUE constraint added successfully")
        except asyncpg.exceptions.DuplicateObjectError:
            logger.warning("UNIQUE constraint already exists, skipping")
        except asyncpg.exceptions.UniqueViolationError as e:
            logger.error("UNIQUE violation after dedup — unexpected: %s", e)

        # 4. Verify no more duplicates
        remaining = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT doc_id, chunk_index
                FROM vector_chunks
                GROUP BY doc_id, chunk_index
                HAVING COUNT(*) > 1
            ) d
        """)
        logger.info("Remaining duplicate groups: %d", remaining)

    finally:
        await conn.close()

    return removed


if __name__ == "__main__":
    removed = asyncio.run(dedup())
    print(f"Done. Removed {removed} duplicate rows.")
