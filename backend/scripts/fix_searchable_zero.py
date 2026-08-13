"""
Fix: Embed searchable=0 docs (with content) into pgvector and set searchable=1.
Also create monitoring script for hollow docs.
"""
import sys, os, json, uuid, sqlite3, time, subprocess, httpx

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"
EMBEDDING_KEY = "66de3c92ba1e435781d9fd8cfc5f6eb1.nxw8tsvAAQu0VVFr"
BATCH_SIZE = 10

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def pg_exec(sql, timeout=30):
    fpath = f"/tmp/_pg_batch_{os.getpid()}.sql"
    with open(fpath, "w") as f: f.write(sql)
    r = subprocess.run(["psql", PG_DSN, "-f", fpath], capture_output=True, text=True, timeout=timeout)
    os.remove(fpath)
    if r.returncode != 0:
        log(f"  ❌ SQL error: {r.stderr[:200]}")

def embed_text(text):
    text = text[:2000]
    if not text.strip(): return None
    resp = httpx.post("https://open.bigmodel.cn/api/paas/v4/embeddings",
        headers={"Authorization": f"Bearer {EMBEDDING_KEY}"},
        json={"model": "embedding-2", "input": text}, timeout=30)
    d = resp.json()
    if d.get("data"): return d["data"][0]["embedding"]
    log(f"  ⚠️ Embed error: {d.get('msg','')[:100]}")
    return None

def main():
    conn = sqlite3.connect(KB_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find searchable=0 docs that have content
    cur.execute("""
        SELECT d.doc_id, d.title, d.hs_bank
        FROM documents d
        WHERE d.searchable = 0 AND d.status = 'active'
          AND EXISTS (SELECT 1 FROM parent_chunks pc WHERE pc.doc_id = d.doc_id AND length(pc.parent_text) > 20)
        ORDER BY d.doc_id
    """)
    docs = cur.fetchall()
    log(f"Found {len(docs)} searchable=0 docs with content to fix")

    for row in docs:
        did = row['doc_id']; title = row['title'] or ""; hb = row['hs_bank'] or "kb_general"
        valid = {"kb_standard","kb_industry","kb_general","kb_xhs","kb_tech","kb_checklist"}
        bk = hb if hb in valid else "kb_general"
        # Map V1 bank names to pgvector bank names
        if bk == "咨询": bk = "kb_xhs"
        
        cur.execute("SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=? AND length(parent_text)>20 ORDER BY parent_idx", (did,))
        chunks = cur.fetchall()
        
        if not chunks:
            log(f"  SKIP {did[:12]}: no chunks >20 chars")
            continue
        
        log(f"  Embedding {title[:40]} ({bk}, {len(chunks)} chunks)...")
        
        buf = []; err = 0
        for idx, text in chunks:
            emb = embed_text(text)
            if emb is None:
                err += 1; continue
            cid = str(uuid.uuid4())
            meta = json.dumps({"title": title}, ensure_ascii=False)
            et = text[:2000].replace("'", "''")
            em = meta.replace("'", "''")
            ev = "[" + ",".join(str(x) for x in emb) + "]"
            buf.append(f"('{cid}'::uuid, '{did}', {idx}, '{bk}', '{et}', '{em}'::jsonb, '{ev}'::vector, now())")
            
            if len(buf) >= BATCH_SIZE:
                sql = "INSERT INTO vector_chunks (id,doc_id,chunk_index,bank,content,metadata,embedding,created_at) VALUES\n" + ",\n".join(buf) + "\nON CONFLICT (id) DO NOTHING;"
                pg_exec(sql)
                buf = []
        
        if buf:
            sql = "INSERT INTO vector_chunks (id,doc_id,chunk_index,bank,content,metadata,embedding,created_at) VALUES\n" + ",\n".join(buf) + "\nON CONFLICT (id) DO NOTHING;"
            pg_exec(sql)
        
        # Verify pgvector insertion
        r = subprocess.run(["psql", PG_DSN, "-tA", "-c", f"SELECT COUNT(*) FROM vector_chunks WHERE doc_id='{did}'"],
                         capture_output=True, text=True, timeout=10, env={"PGPASSWORD":"hindsight123"})
        pg_count = int(r.stdout.strip())
        
        if pg_count > 0:
            # Set searchable=1
            conn.execute("UPDATE documents SET searchable=1 WHERE doc_id=?", (did,))
            conn.commit()
            log(f"    ✅ {pg_count} chunks embedded → searchable=1")
        else:
            log(f"    ❌ pgvector write failed, keeping searchable=0")

    conn.close()
    
    # Final summary
    r2 = subprocess.run(["psql", PG_DSN, "-tA", "-c", "SELECT COUNT(*) FROM vector_chunks"],
                      capture_output=True, text=True, timeout=10, env={"PGPASSWORD":"hindsight123"})
    total = int(r2.stdout.strip())
    log(f"\nvector_chunks total: {total}")
    log(f"Done.")

if __name__ == "__main__":
    main()
