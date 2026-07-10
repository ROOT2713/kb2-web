"""迁移 hindsight memory_units → vector_chunks。

从 hindsight 数据库的 memory_units 表读取所有数据，
写入 vector_chunks 表（含 embedding）。

处理策略：
- 有 document_id 的 chunk：使用 document_id 作为 doc_id
- 无 document_id 的 orphan chunk：从 tags 中提取 doc_id，如果也没有则使用 mu.id 作为 doc_id
- 使用 tags 字段还原 metadata、chunk_index 等信息
"""
import asyncio
import json
import logging
from typing import List, Dict, Optional, Tuple
from typing import List, Dict, Optional, Tuple

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"


def parse_tags(tags: List[str]) -> Tuple[str, int, Dict]:
    """Parse hindsight tags into (doc_id, chunk_index, metadata_dict)."""
    doc_id: Optional[str] = None
    chunk_index = 0
    metadata: Dict = {}

    for t in tags:
        if ":" not in t:
            continue
        k, v = t.split(":", 1)
        if k == "doc_id":
            doc_id = v
        elif k == "chunk":
            # Format: "N/M"
            parts = v.split("/")
            try:
                chunk_index = int(parts[0])
            except (ValueError, IndexError):
                pass
        elif k == "parent_idx":
            try:
                metadata["parent_idx"] = int(v)
            except ValueError:
                metadata["parent_idx"] = v
        else:
            metadata[k] = v

    return doc_id or "", chunk_index, metadata


async def migrate():
    logger.info("Starting migration from memory_units to vector_chunks...")

    conn = await asyncpg.connect(DB_URL)

    # Read all memory_units with their document info
    rows = await conn.fetch("""
        SELECT
            mu.id AS mu_id,
            mu.bank_id,
            mu.document_id,
            mu.text,
            mu.embedding,
            mu.tags,
            mu.metadata,
            mu.created_at,
            mu.chunk_id
        FROM public.memory_units mu
        ORDER BY mu.created_at
    """)
    logger.info("Read %d memory_units from source", len(rows))

    # Build batch insert rows
    insert_rows: List[tuple] = []
    skipped = 0
    orphan_count = 0

    for r in rows:
        mu_id = r["mu_id"]
        bank = r["bank_id"]
        doc_id_raw = r["document_id"]
        text = r["text"]
        embedding = r["embedding"]
        tags_arr = list(r["tags"] or [])
        mu_metadata_raw = r["metadata"]
        mu_metadata = json.loads(mu_metadata_raw) if isinstance(mu_metadata_raw, str) else (mu_metadata_raw or {})
        created_at = r["created_at"]
        chunk_id = r["chunk_id"]

        # Parse tags to extract doc_id, chunk_index, and metadata
        tag_doc_id, chunk_index, tag_metadata = parse_tags(tags_arr)

        # Determine final doc_id: document_id > tag doc_id > mu_id
        final_doc_id = doc_id_raw or tag_doc_id or str(mu_id)
        if not doc_id_raw:
            orphan_count += 1

        # Merge metadata: tag_metadata takes precedence, then mu_metadata
        merged_metadata = {**mu_metadata, **tag_metadata}
        if chunk_id:
            merged_metadata["chunk_id"] = chunk_id

        # Convert embedding to list
        emb_list = list(embedding) if embedding else None

        insert_rows.append((
            str(mu_id),
            final_doc_id,
            chunk_index,
            bank,
            text,
            merged_metadata,
            emb_list,
            created_at,
        ))

    logger.info("Prepared %d rows (%d orphans without document_id)", len(insert_rows), orphan_count)

    # Batch insert into vector_chunks using COPY (fastest for bulk vector data)
    inserted = 0
    # Use COPY with text format: each row is tab-separated, NULL as \\N
    import io
    buf = io.StringIO()
    for row in insert_rows:
        mu_id, doc_id, chunk_idx, bank, text, metadata, emb_list, created_at = row
        # Format embedding as pgvector text format: '[0.1,0.2,...]'
        emb_str = "[" + ",".join(f"{v}" for v in emb_list) + "]" if emb_list else "\\N"
        meta_str = json.dumps(metadata, ensure_ascii=False).replace("\n", " ") if metadata else "{}"
        text_escaped = text.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", " ")
        buf.write(f"{mu_id}\t{doc_id}\t{chunk_idx}\t{bank}\t{text_escaped}\t{meta_str}\t{emb_str}\t{created_at}\n")
        inserted += 1
        if inserted % 1000 == 0:
            logger.info("Prepared %d / %d rows for COPY", inserted, len(insert_rows))
    
    buf.seek(0)
    logger.info("Starting COPY of %d rows...", len(insert_rows))
    try:
        await conn.copy_from_table(
            "vector_chunks",
            columns=["id", "doc_id", "chunk_index", "bank", "content", "metadata", "embedding", "created_at"],
            source=buf.getvalue(),
            format="text",
        )
    except Exception:
        # Fallback: copy from stream
        buf.seek(0)
        await conn.copy_to_table(
            "vector_chunks",
            columns=["id", "doc_id", "chunk_index", "bank", "content", "metadata", "embedding", "created_at"],
            source=buf,
            format="text",
        )
    logger.info("COPY complete: %d rows inserted", inserted)

    # Verify counts
    count = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks")
    logger.info("Migration complete: vector_chunks has %d rows (source: %d)", count, len(insert_rows))

    await conn.close()
    return count


async def main():
    count = await migrate()
    print(f"\n=== Migration finished: {count} rows in vector_chunks ===")


if __name__ == "__main__":
    asyncio.run(main())
