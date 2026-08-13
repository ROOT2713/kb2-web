#!/usr/bin/env python3
"""Fix hollow doc using asyncpg with register_vector + JSONB fix."""

import sqlite3, json, time, httpx, asyncio, asyncpg
from pgvector.asyncpg import register_vector

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"
EMBEDDING_KEY = "66de3c92ba1e435781d9fd8cfc5f6eb1.nxw8tsvAAQu0VVFr"
DOC_ID = "276ebaa4-bac8-41c5-bbee-c4e1bcd5143c"

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

async def embed_text(text):
    text = text[:2000]
    if not text.strip():
        return None
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://open.bigmodel.cn/api/paas/v4/embeddings",
            headers={"Authorization": f"Bearer {EMBEDDING_KEY}"},
            json={"model": "embedding-2", "input": text}
        )
        d = resp.json()
        if d.get("data"):
            return d["data"][0]["embedding"]
        log(f"  ⚠️ Embed error: {d.get('msg','')[:100]}")
        return None

async def main():
    db = sqlite3.connect(KB_DB)
    db.row_factory = sqlite3.Row

    # Standard register_vector + JSONB fix pattern (from vector_repo.py)
    conn = await asyncpg.connect(PG_DSN)
    await register_vector(conn)
    await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')

    try:
        doc = db.execute("SELECT * FROM documents WHERE doc_id=?", (DOC_ID,)).fetchone()
        if not doc:
            log("❌ Doc not found")
            return
        log(f"Doc: {doc['title']} (bank={doc['hs_bank']})")

        chunks = db.execute(
            "SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=? AND length(parent_text)>20 ORDER BY parent_idx",
            (DOC_ID,)
        ).fetchall()
        log(f"Found {len(chunks)} chunks")

        if not chunks:
            return

        # Delete old
        await conn.execute("DELETE FROM vector_chunks WHERE doc_id = $1", DOC_ID)
        log("Deleted old pgvector entries")

        total = len(chunks)
        inserted = 0
        for i, c in enumerate(chunks):
            text = c["parent_text"]
            emb = await embed_text(text)
            if not emb:
                continue

            meta = json.dumps({
                "title": doc["title"],
                "category": doc["category"] or "",
                "bank": doc["hs_bank"] or "kb_general",
            }, ensure_ascii=False)

            # register_vector allows passing list directly for vector type
            await conn.execute(
                "INSERT INTO vector_chunks (doc_id, chunk_index, content, metadata, embedding, bank) VALUES ($1, $2, $3, $4::jsonb, $5, $6)",
                DOC_ID, c["parent_idx"], text, meta, emb, doc["hs_bank"] or "kb_general"
            )
            inserted += 1
            if inserted % 3 == 0:
                log(f"  {inserted}/{total} embedded")

        log(f"✅ Inserted {inserted} chunks to pgvector")

        # Verify
        cnt = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks WHERE doc_id = $1", DOC_ID)
        log(f"pgvector chunks after fix: {cnt}")
    finally:
        await conn.close()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
