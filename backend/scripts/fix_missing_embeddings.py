#!/usr/bin/env python3
"""Fix missing pgvector embedding for specific doc."""

import sqlite3, json, asyncio, asyncpg, logging, httpx
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"
ZHIPU_KEY = "227e20a001e59dc178b79aff8fb49c87.zN6eG4s0a3s3jFzu"
EMBED_URL = "https://open.bigmodel.cn/api/paas/v4/model-api/embedding-2/embeddings"

DOC_IDS = [
    "276ebaa4-bac8-41c5-bbee-c4e1bcd5143c",  # 等级保护测评过程指南
]

async def get_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            EMBED_URL,
            headers={"Authorization": f"Bearer {ZHIPU_KEY}"},
            json={"input": text[:1800], "model": "embedding-2"},
        )
        if resp.status_code != 200:
            logger.error("embedding API error %s: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json()
        emb = data.get("data", [{}])[0].get("embedding", [])
        # Zhipu returns raw floats, convert to str for pgvector
        return emb

async def fix_doc(doc_id: str):
    db = sqlite3.connect(KB_DB)
    db.row_factory = sqlite3.Row
    conn = await asyncpg.connect(PG_DSN)

    try:
        doc = db.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if not doc:
            logger.error("Doc %s not found", doc_id)
            return

        title = doc["title"]
        bank = doc["hs_bank"] or "general"
        category = doc["category"] or ""
        logger.info("Fixing doc: %s (%s) bank=%s", title[:40], doc_id[:12], bank)

        chunks = db.execute(
            "SELECT * FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
            (doc_id,)
        ).fetchall()

        if not chunks:
            logger.warning("No parent_chunks for %s", doc_id)
            return

        # Delete existing pgvector entries
        await conn.execute("DELETE FROM vector_chunks WHERE doc_id = $1", doc_id)

        # Insert each chunk with embedding
        inserted = 0
        for i, c in enumerate(chunks):
            text = c["parent_text"][:1800]
            emb = await get_embedding(text)
            if not emb:
                logger.warning("Skip chunk %d: empty embedding", i)
                continue

            meta = json.dumps({
                "title": title,
                "category": category,
                "bank": bank,
            })
            emb_str = ",".join(str(x) for x in emb)
            sql = f"""
                INSERT INTO vector_chunks (doc_id, chunk_index, content, metadata, embedding, bank)
                VALUES ($1, $2, $3, $4::jsonb, '[{emb_str}]'::vector, $5)
            """
            await conn.execute(sql, doc_id, i, text, meta, bank)
            inserted += 1
            if inserted % 5 == 0:
                logger.info("  inserted %d/%d chunks", inserted, len(chunks))

        logger.info("Done: %s — inserted %d chunks", doc_id[:12], inserted)

        # Also fix searchable to 1
        db.execute("UPDATE documents SET searchable=1 WHERE doc_id=?", (doc_id,))
        db.commit()

    finally:
        await conn.close()
        db.close()

async def main():
    for did in DOC_IDS:
        await fix_doc(did)

if __name__ == "__main__":
    asyncio.run(main())
    print("All done.")
