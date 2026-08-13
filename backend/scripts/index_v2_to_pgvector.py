"""
Standalone script: index V2 documents from SQLite parent_chunks into pgvector vector_chunks.
No dependency on kb2-web app code — uses direct sqlite3 + asyncpg + httpx.
"""
import sys, os, json, uuid, sqlite3, argparse, asyncio, httpx, asyncpg
from datetime import datetime, timezone
from io import StringIO

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"
EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
EMBEDDING_KEY = "66de3c92ba1e435781d9fd8cfc5f6eb1.nxw8tsvAAQu0VVFr"
EMBEDDING_MODEL = "embedding-2"

INSERT_SQL = """
    INSERT INTO vector_chunks (id, doc_id, chunk_index, bank, content, metadata, embedding, created_at)
    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::vector, $8)
    ON CONFLICT (id) DO NOTHING
"""
BATCH_MAX = 5  # concurrent docs

def log(m):
    print(m, flush=True)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exec", action="store_true")
    parser.add_argument("--batch", type=int, default=3)
    args = parser.parse_args()
    if not args.exec and not args.dry_run:
        print("Use --dry-run or --exec"); return

    mode = "DRY RUN" if args.dry_run else "EXEC"
    log(f"=== {mode}: connecting to SQLite...")

    conn = sqlite3.connect(KB_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Read V2 docs with parent_chunks
    cur.execute("""
        SELECT d.doc_id, d.title, d.hs_bank
        FROM documents d
        JOIN parent_chunks pc ON pc.doc_id = d.doc_id
        WHERE d.searchable = 1 AND d.status = 'active'
          AND LENGTH(pc.parent_text) > 20
        GROUP BY d.doc_id
        ORDER BY d.doc_id
    """)
    rows = cur.fetchall()
    log(f"  V2 documents: {len(rows)}")

    valid_banks = {"kb_standard", "kb_industry", "kb_general", "kb_xhs", "kb_tech", "kb_checklist"}
    doc_batches = []
    total_chunks = 0

    for row in rows:
        doc_id = row['doc_id']; title = row['title'] or ""; hs_bank = row['hs_bank']
        pg_bank = hs_bank if hs_bank in valid_banks else "kb_general"
        cur.execute("SELECT parent_idx, parent_text FROM parent_chunks "
                    "WHERE doc_id=? AND length(parent_text)>20 ORDER BY parent_idx", (doc_id,))
        chunks = [(r[0], r[1]) for r in cur.fetchall()]
        total_chunks += len(chunks)
        doc_batches.append((doc_id, title, pg_bank, chunks))

    conn.close()
    log(f"  Total chunks: {total_chunks}")

    if args.dry_run:
        for doc_id, title, pg_bank, chunks in doc_batches[:5]:
            log(f"  {doc_id[:12]}  {str(title)[:40]:40s}  bank={pg_bank:15s}  {len(chunks)} chunks")
        if len(doc_batches) > 5:
            log(f"  ... and {len(doc_batches) - 5} more docs")
        log("  → Run with --exec to actually insert")
        return

    # Connect pgvector
    log("  Connecting to pgvector...")
    pool = await asyncpg.create_pool(PG_DSN, min_size=args.batch, max_size=args.batch + 2)
    async with pool.acquire() as pg:
        before = await pg.fetchval("SELECT COUNT(*) FROM vector_chunks")
    log(f"  Existing vector_chunks: {before}")

    # Stats
    inserted = 0; skipped = 0; errors = 0; api_calls = 0

    async def process_one(pool, client, doc_id, title, bank, chunks):
        nonlocal inserted, skipped, errors, api_calls
        async with pool.acquire() as pg:
            for idx, text in chunks:
                if not text or len(text.strip()) < 20:
                    skipped += 1; continue
                # Embedding
                resp = await client.post(EMBEDDING_URL, json={
                    "model": EMBEDDING_MODEL, "input": text[:2000],
                }, timeout=30)
                data = resp.json()
                if not data.get("data"):
                    errors += 1
                    log(f"  ⚠️ Embed API error for {doc_id[:8]}[{idx}]: {data.get('msg','')[:100]}")
                    continue
                api_calls += 1
                emb = data["data"][0]["embedding"]
                emb_str = "[" + ",".join(str(x) for x in emb) + "]"

                cid = uuid.uuid4()
                meta = json.dumps({"title": title}, ensure_ascii=False)
                try:
                    await pg.execute(INSERT_SQL, cid, doc_id, idx, bank,
                                     text[:2000], meta, emb_str, datetime.now(timezone.utc))
                    inserted += 1
                except Exception as e:
                    errors += 1
                    log(f"  ❌ [{doc_id[:8]}][{idx}]: {str(e)[:80]}")

    async with httpx.AsyncClient(headers={
        "Authorization": f"Bearer {EMBEDDING_KEY}",
        "Content-Type": "application/json",
    }, timeout=30) as client:

        sem = asyncio.Semaphore(args.batch)

        async def bounded(doc_id, title, bank, chunks):
            async with sem:
                await process_one(pool, client, doc_id, title, bank, chunks)

        tasks = [bounded(doc_id, title, bank, chunks)
                 for doc_id, title, bank, chunks in doc_batches]

        for i in range(0, len(tasks), BATCH_MAX):
            await asyncio.gather(*tasks[i:i+BATCH_MAX])
            log(f"  Batch {i//BATCH_MAX+1}/{(len(tasks)-1)//BATCH_MAX+1}: "
                f"ins={inserted} err={errors} api={api_calls}")

    # Verify
    async with pool.acquire() as pg:
        after = await pg.fetchval("SELECT COUNT(*) FROM vector_chunks")
        new_docs = await pg.fetchval("SELECT COUNT(DISTINCT doc_id) FROM vector_chunks "
            "WHERE bank IN ('kb_standard','kb_industry','kb_general','kb_xhs')")
    log(f"  vector_chunks: {before} → {after} (+{after - before})")
    log(f"  V2 doc_ids in pgvector: {new_docs}")
    log(f"✅ Done. inserted={inserted} skipped={skipped} errors={errors} api_calls={api_calls}")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
