"""
V2 index script v3 - uses psql INSERT batches.
"""
import sys, os, json, uuid, sqlite3, argparse, time, subprocess, httpx

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"
EMBEDDING_KEY = "66de3c92ba1e435781d9fd8cfc5f6eb1.nxw8tsvAAQu0VVFr"
BATCH_SIZE = 5

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def pg_count(sql):
    r = subprocess.run(["psql", PG_DSN, "-tA", "-c", sql], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        log(f"  ❌ SQL error: {r.stderr[:200]}")
        return 0
    return int(r.stdout.strip())

def pg_exec(sql, timeout=30):
    fpath = f"/tmp/_pg_batch_{os.getpid()}.sql"
    with open(fpath, "w") as f:
        f.write(sql)
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

def load_docs(limit=0, skip=0):
    conn = sqlite3.connect(KB_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    sql = "SELECT d.doc_id, d.title, d.hs_bank FROM documents d "\
          "JOIN parent_chunks pc ON pc.doc_id = d.doc_id "\
          "WHERE d.searchable=1 AND d.status='active' AND LENGTH(pc.parent_text)>20 "\
          "GROUP BY d.doc_id ORDER BY d.doc_id"
    params = []
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    if skip:
        sql += " OFFSET ?"
        params.append(skip)
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    valid = {"kb_standard","kb_industry","kb_general","kb_xhs","kb_tech","kb_checklist"}
    docs = []; tc = 0
    for r in rows[:limit] if limit else rows:
        bk = r['hs_bank'] if r['hs_bank'] in valid else "kb_general"
        cur.execute("SELECT parent_idx, parent_text FROM parent_chunks "
                    "WHERE doc_id=? AND length(parent_text)>20 ORDER BY parent_idx", (r['doc_id'],))
        ch = [(x[0], x[1]) for x in cur.fetchall()]
        tc += len(ch)
        docs.append((r['doc_id'], r['title'] or "", bk, ch))
    conn.close()
    return docs, tc

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exec", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip", type=int, default=0)
    args = parser.parse_args()
    if not args.exec and not args.dry_run:
        print("Use --dry-run or --exec"); return

    docs, tc = load_docs(args.limit, args.skip)
    log(f"Docs: {len(docs)}, chunks: {tc}")

    before = pg_count("SELECT COUNT(*) FROM vector_chunks")
    log(f"Existing: {before}")

    if args.dry_run:
        for d, t, b, c in docs[:5]:
            log(f"  {d[:12]} {str(t)[:40]} bank={b} chunks={len(c)}")
        log(f"Done.")
        return

    ins = 0; err = 0; calls = 0; skip = 0
    buf = []; bn = 0

    for di, (did, title, bk, chunks) in enumerate(docs):
        log(f"[{di+1}/{len(docs)}] {title[:40]} ({bk}, {len(chunks)} ch)")
        for idx, text in chunks:
            if not text or len(text.strip()) < 20:
                skip += 1; continue
            emb = embed_text(text)
            if emb is None: err += 1; continue
            calls += 1
            cid = str(uuid.uuid4())
            meta = json.dumps({"title": title}, ensure_ascii=False)
            et = text[:2000].replace("'", "''")
            em = meta.replace("'", "''")
            ev = "[" + ",".join(str(x) for x in emb) + "]"
            buf.append(f"('{cid}'::uuid, '{did}', {idx}, '{bk}', '{et}', '{em}'::jsonb, '{ev}'::vector, now())")
            ins += 1
            if len(buf) >= BATCH_SIZE:
                bn += 1
                sql = "INSERT INTO vector_chunks (id,doc_id,chunk_index,bank,content,metadata,embedding,created_at) VALUES\n" + ",\n".join(buf) + "\nON CONFLICT (id) DO NOTHING;"
                pg_exec(sql)
                buf = []
        if (di+1) % 5 == 0:
            log(f"  CP: ins={ins} err={err} api={calls} skip={skip}")

    if buf:
        bn += 1
        sql = "INSERT INTO vector_chunks (id,doc_id,chunk_index,bank,content,metadata,embedding,created_at) VALUES\n" + ",\n".join(buf) + "\nON CONFLICT (id) DO NOTHING;"
        log(f"  Final batch ({len(buf)} rows)...")
        pg_exec(sql, timeout=60)

    after = pg_count("SELECT COUNT(*) FROM vector_chunks")
    nd = pg_count("SELECT COUNT(DISTINCT doc_id) FROM vector_chunks WHERE bank IN ('kb_standard','kb_industry','kb_general','kb_xhs')")
    log(f"\nvector_chunks: {before} → {after} (+{after-before})")
    log(f"V2 doc_ids: {nd}")
    log(f"Done. ins={ins} skip={skip} err={err} api={calls}")

if __name__ == "__main__":
    main()
