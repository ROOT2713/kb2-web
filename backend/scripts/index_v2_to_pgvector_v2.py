"""
Sync script: index V2 docs from SQLite parent_chunks into pgvector.
Uses sync httpx + psql COPY (no asyncpg) for reliability.
Run foreground: python3 scripts/index_v2_to_pgvector_v2.py --exec --limit 20
"""
import sys, os, json, uuid, sqlite3, argparse, time, subprocess, tempfile

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"
EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
EMBEDDING_KEY = "66de3c92ba1e435781d9fd8cfc5f6eb1.nxw8tsvAAQu0VVFr"
EMBEDDING_MODEL = "embedding-2"

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def sqlite_docs(limit=0):
    conn = sqlite3.connect(KB_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
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
    valid_banks = {"kb_standard", "kb_industry", "kb_general", "kb_xhs", "kb_tech", "kb_checklist"}
    docs = []
    total_chunks = 0
    for row in rows[:limit] if limit else rows:
        doc_id = row['doc_id']; title = row['title'] or ""; hs_bank = row['hs_bank']
        bank = hs_bank if hs_bank in valid_banks else "kb_general"
        cur.execute("SELECT parent_idx, parent_text FROM parent_chunks "
                    "WHERE doc_id=? AND length(parent_text)>20 ORDER BY parent_idx", (doc_id,))
        chunks = [(r[0], r[1]) for r in cur.fetchall()]
        total_chunks += len(chunks)
        docs.append((doc_id, title, bank, chunks))
    conn.close()
    return docs, total_chunks

def get_embedding(text):
    import httpx
    text = text[:2000]
    if not text.strip():
        return None
    resp = httpx.post(EMBEDDING_URL,
        headers={"Authorization": f"Bearer {EMBEDDING_KEY}"},
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=30)
    data = resp.json()
    if data.get("data"):
        return data["data"][0]["embedding"]
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exec", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Limit docs to process")
    args = parser.parse_args()
    if not args.exec and not args.dry_run:
        print("Use --dry-run or --exec"); return

    # Read docs from SQLite
    docs, total_chunks = sqlite_docs(args.limit)
    log(f"Docs: {len(docs)}, chunks: {total_chunks}")

    if args.dry_run:
        for doc_id, title, bank, chunks in docs[:5]:
            log(f"  {doc_id[:12]} {str(title)[:40]} bank={bank} chunks={len(chunks)}")
        if len(docs) > 5:
            log(f"  ... and {len(docs)-5} more")
        # Check existing pgvector count
        import asyncpg, asyncio
        async def check():
            conn = await asyncpg.connect(PG_DSN)
            n = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks")
            await conn.close()
            return n
        before = asyncio.run(check())
        log(f"Existing vector_chunks: {before}")
        log("Done. Use --exec to insert")
        return

    # Get existing count
    import asyncpg, asyncio
    async def get_count():
        conn = await asyncpg.connect(PG_DSN)
        n = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks")
        await conn.close()
        return n
    before = asyncio.run(get_count())
    log(f"Existing vector_chunks: {before}")

    # Process: embed → write to temp CSV → psql COPY
    inserted = 0; errors = 0; api_calls = 0; skipped = 0
    tsv_path = "/tmp/pgvector_insert.tsv"
    
    with open(tsv_path, "w") as f:
        f.write("")  # clear
    rows_buf = []
    
    for doc_idx, (doc_id, title, bank, chunks) in enumerate(docs):
        log(f"Doc {doc_idx+1}/{len(docs)}: {title[:40]}")
        for idx, text in chunks:
            if not text or len(text.strip()) < 20:
                skipped += 1; continue
            emb = get_embedding(text)
            if emb is None:
                errors += 1
                log(f"  ❌ Embed error: {doc_id[:8]}[{idx}]")
                continue
            api_calls += 1
            
            cid = str(uuid.uuid4())
            meta = json.dumps({"title": title}, ensure_ascii=False)
            emb_str = "[" + ",".join(str(x) for x in emb) + "]"
            now = time.strftime("%Y-%m-%d %H:%M:%S+00")
            
            # Write to TSV (escaped for PostgreSQL COPY)
            # Escape: tab, newline, backslash in fields
            def esc(s):
                return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
            
            line = f"{cid}\t{doc_id}\t{idx}\t{bank}\t{esc(text)}\t{esc(meta)}\t{emb_str}\t{now}\n"
            
            with open(tsv_path, "a") as f:
                f.write(line)
            
            inserted += 1
        
        # Flush every 5 docs
        if (doc_idx + 1) % 5 == 0:
            log(f"  Checkpoint: ins={inserted} err={errors} api={api_calls} skipped={skipped}")

    # COPY via psql
    log(f"\nCOPYING {inserted} rows to pgvector via psql...")
    copy_sql = f"""
        CREATE TEMP TABLE _stage (
            id UUID, doc_id TEXT, chunk_index INT, bank TEXT,
            content TEXT, metadata TEXT, embedding TEXT, created_at TIMESTAMPTZ
        ) ON COMMIT DROP;
        \copy _stage FROM '{tsv_path}' WITH (FORMAT TEXT, DELIMITER E'\\t', NULL '\\N');
        INSERT INTO vector_chunks (id, doc_id, chunk_index, bank, content, metadata, embedding, created_at)
        SELECT s.id, s.doc_id, s.chunk_index, s.bank, s.content,
               s.metadata::jsonb, s.embedding::vector, s.created_at
        FROM _stage s
        WHERE NOT EXISTS (SELECT 1 FROM vector_chunks v WHERE v.id = s.id);
    """
    
    # Write SQL to temp file to avoid shell escaping issues
    sql_path = "/tmp/_pg_copy.sql"
    with open(sql_path, "w") as f:
        f.write(copy_sql)
    
    result = subprocess.run(
        ["psql", PG_DSN, "-f", sql_path],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        log(f"❌ COPY error: {result.stderr[:200]}")
        return
    
    # Verify
    async def verify():
        conn = await asyncpg.connect(PG_DSN)
        after = await conn.fetchval("SELECT COUNT(*) FROM vector_chunks")
        new_docs = await conn.fetchval("SELECT COUNT(DISTINCT doc_id) FROM vector_chunks "
            "WHERE bank IN ('kb_standard','kb_industry','kb_general','kb_xhs')")
        await conn.close()
        return after, new_docs
    
    after, new_docs = asyncio.run(verify())
    log(f"\nvector_chunks: {before} → {after} (+{after - before})")
    log(f"V2 doc_ids in pgvector: {new_docs}")
    log(f"Done. inserted={inserted} skipped={skipped} errors={errors} api={api_calls}")

    # Cleanup
    os.remove(tsv_path)

if __name__ == "__main__":
    main()
