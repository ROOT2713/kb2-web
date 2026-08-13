-- Safe dedup without TRUNCATE.
-- Strategy: delete dup rows (keep only the row with longest metadata per doc_id/chunk_index),
-- then add UNIQUE constraint.
--
-- No ACCESS EXCLUSIVE lock needed; runs as normal DELETE within a transaction.
-- If it fails mid-way, rollback is safe — no data loss.

BEGIN;

SELECT 'Before' AS phase, COUNT(*) AS cnt FROM vector_chunks;

-- Use PostgreSQL's ctid (physical row ID) for targeted deletes.
-- For each (doc_id, chunk_index) group, keep the row with the longest metadata,
-- delete all others.
DELETE FROM vector_chunks v
WHERE EXISTS (
    SELECT 1 FROM vector_chunks v2
    WHERE v2.doc_id = v.doc_id
      AND v2.chunk_index = v.chunk_index
      AND (
          -- prefer longer metadata (more complete fields)
          LENGTH(v2.metadata::text) > LENGTH(v.metadata::text)
          OR (
              -- tie-break: if same metadata length, prefer longer content
              LENGTH(v2.metadata::text) = LENGTH(v.metadata::text)
              AND LENGTH(v2.content) > LENGTH(v.content)
          )
          OR (
              -- if metadata & content both equal length, keep lower ctid (older row)
              LENGTH(v2.metadata::text) = LENGTH(v.metadata::text)
              AND LENGTH(v2.content) = LENGTH(v.content)
              AND v2.ctid < v.ctid
          )
      )
);

SELECT 'After dedup' AS phase, COUNT(*) AS cnt FROM vector_chunks;

SELECT 'Remaining dup groups' AS phase, COUNT(*) AS cnt FROM (
    SELECT doc_id, chunk_index
    FROM vector_chunks
    GROUP BY doc_id, chunk_index
    HAVING COUNT(*) > 1
) d;

ALTER TABLE vector_chunks
ADD CONSTRAINT vector_chunks_doc_id_chunk_idx_key
UNIQUE (doc_id, chunk_index);

COMMIT;
