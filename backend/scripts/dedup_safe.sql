-- Safe dedup of vector_chunks using DELETE with ROW_NUMBER subquery.
-- 
-- Root cause: fix_searchable_zero.py INSERTed rows without pre-deleting,
-- creating 17K+ duplicate (doc_id, chunk_index) pairs. When the query
-- pipeline picks an arbitrary row from a duplicate group, it may get
-- the short-metadata variant, producing empty title/category/content.
--
-- Strategy: dedup first, then add UNIQUE constraint to prevent recurrence.

BEGIN;

SELECT 'Before dedup' AS info, COUNT(*) AS cnt FROM vector_chunks;

-- Step 1: Use tableoid + ctid as stable row identifier for DELETE
-- We delete rows where a higher-ranked (longer metadata) sibling exists
-- within the same (doc_id, chunk_index) group.
-- 
-- This is safe because: within a single DELETE statement, ctid is stable,
-- and the subquery runs under the same snapshot.
DELETE FROM vector_chunks v
WHERE EXISTS (
    SELECT 1 FROM vector_chunks v2
    WHERE v2.doc_id = v.doc_id
      AND v2.chunk_index = v.chunk_index
      AND (
          LENGTH(v2.metadata::text) > LENGTH(v.metadata::text)
          OR (
              LENGTH(v2.metadata::text) = LENGTH(v.metadata::text)
              AND v2.ctid > v.ctid
          )
      )
);

-- Step 2: Count remaining
SELECT 'After dedup' AS info, COUNT(*) AS cnt FROM vector_chunks;

-- Step 3: Verify no duplicates remain
SELECT 'Remaining dup groups' AS info, COUNT(*) AS cnt FROM (
    SELECT doc_id, chunk_index
    FROM vector_chunks
    GROUP BY doc_id, chunk_index
    HAVING COUNT(*) > 1
) d;

-- Step 4: Add UNIQUE constraint
ALTER TABLE vector_chunks
ADD CONSTRAINT vector_chunks_doc_id_chunk_idx_key
UNIQUE (doc_id, chunk_index);

COMMIT;
