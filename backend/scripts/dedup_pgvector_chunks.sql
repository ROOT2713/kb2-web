-- Deduplicate vector_chunks: for each (doc_id, chunk_index), keep the row with
-- the longest (most complete) metadata, delete all others.
-- Then add a UNIQUE constraint to prevent recurrence.

BEGIN;

-- Step 1: Identify duplicates using the internal 'ctid' (physical row ID)
-- We use a two-step approach: first into temp table, then delete.
CREATE TEMP TABLE dedup_keep AS
SELECT MIN(ctid) AS keep_ctid, doc_id, chunk_index, COUNT(*) AS cnt
FROM vector_chunks
GROUP BY doc_id, chunk_index
HAVING COUNT(*) = 1;

CREATE TEMP TABLE dedup_dup AS
SELECT ctid, doc_id, chunk_index,
       ROW_NUMBER() OVER (
           PARTITION BY doc_id, chunk_index
           ORDER BY LENGTH(metadata::text) DESC, LENGTH(content) DESC
       ) AS rn
FROM vector_chunks
WHERE (doc_id, chunk_index) IN (
    SELECT doc_id, chunk_index
    FROM vector_chunks
    GROUP BY doc_id, chunk_index
    HAVING COUNT(*) > 1
);

-- Keep rn=1 (longest metadata), delete the rest
DELETE FROM vector_chunks
WHERE ctid IN (
    SELECT ctid FROM dedup_dup WHERE rn > 1
);

DROP TABLE dedup_keep;
DROP TABLE dedup_dup;

-- Step 2: Count remaining (should match unique groups)
SELECT 'Remaining rows' AS info, COUNT(*) FROM vector_chunks;
SELECT 'Duplicate groups remaining' AS info, COUNT(*) FROM (
    SELECT doc_id, chunk_index
    FROM vector_chunks
    GROUP BY doc_id, chunk_index
    HAVING COUNT(*) > 1
) d;

-- Step 3: Add UNIQUE constraint
ALTER TABLE vector_chunks
ADD CONSTRAINT vector_chunks_doc_id_chunk_index_key
UNIQUE (doc_id, chunk_index);

COMMIT;
