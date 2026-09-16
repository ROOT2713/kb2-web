#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-0 修 bank 维度残留（FIX-P2-G1 的历史产物）

背景: 旧 delete/upsert 按 (doc_id, bank) 二元条件删除 —— 文档换 bank 后旧 bank
      的向量删不掉，成为"跨 bank 残留"。FIX-P2-G1 已修代码，本脚本清历史残留。

判据: doc_id 是 UUID 全局唯一 → 同一 doc_id 的向量只应属于一个 bank。
      权威 bank 取 SQLite documents.hs_bank（缺失则 bank）。

用法:
    python3 p2_fix_bank_residue.py            # dry-run，列出将删行
    python3 p2_fix_bank_residue.py --apply    # 建备份表 + 删除
"""
import argparse
import os
import sqlite3
import time

ENV = "/home/ubuntu/kb2-web/backend/.env"
SQLITE_CANDIDATES = [
    "/home/ubuntu/kb-web/data/kb.db",
    "/home/ubuntu/kb2-web/backend/data/kb.db",
]


def dsn() -> str:
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            if line.startswith("pgvector_database_url"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("未找到 pgvector_database_url")


def pick_sqlite() -> str:
    best, best_n = None, -1
    for p in SQLITE_CANDIDATES:
        if not os.path.exists(p):
            continue
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                n = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            finally:
                con.close()
            if n > best_n:
                best, best_n = p, n
        except Exception:
            continue
    if best is None:
        raise SystemExit("未找到含 documents 表的库")
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import psycopg2

    db = pick_sqlite()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    canon = {}
    for r in con.execute("SELECT doc_id, hs_bank, bank, status FROM documents"):
        canon[r[0]] = {"canonical": r[1] or r[2], "status": r[3]}
    con.close()

    pg = psycopg2.connect(dsn())
    pg.autocommit = False
    cur = pg.cursor()

    cur.execute("""
        SELECT doc_id, bank, COUNT(*) FROM vector_chunks
        WHERE doc_id IN (
            SELECT doc_id FROM vector_chunks
            GROUP BY doc_id HAVING COUNT(DISTINCT bank) > 1
        )
        GROUP BY doc_id, bank ORDER BY doc_id, bank
    """)
    by_doc = {}
    for d, b, n in cur.fetchall():
        by_doc.setdefault(d, []).append((b, n))

    print(f"SQLite: {db}")
    print(f"跨 bank 残留 doc 数: {len(by_doc)}\n")

    cur.execute("CREATE TEMP TABLE _canon (doc_id text primary key, canonical text)")
    plan = []
    for d, banks in by_doc.items():
        info = canon.get(d)
        if info is None:
            print(f"  ⚠️  {d[:8]} 不在 SQLite documents（孤儿） banks={banks} → 跳过，另行处置")
            continue
        c = info["canonical"]
        pg_banks = {b for b, _ in banks}
        if c not in pg_banks:
            print(f"  ⚠️  {d[:8]} 权威 bank={c!r} 不在 pg banks={sorted(pg_banks)} → 跳过（需人工判断）")
            continue
        drop = [(b, n) for b, n in banks if b != c]
        plan.append((d, c, drop, info["status"]))
        print(f"  权威 bank={c!r}  保留 {[n for b, n in banks if b == c][0]} 行 | "
              f"待删 {drop}  status={info['status']}")

    if not plan:
        print("\n无需清理。")
        pg.close()
        return

    if not args.apply:
        print(f"\n[dry-run] {len(plan)} 个 doc 有待删残留行。加 --apply 执行。")
        pg.close()
        return

    for d, c, _drop, _st in plan:
        cur.execute("INSERT INTO _canon VALUES (%s, %s)", (d, c))
    cur.execute("""
        SELECT COUNT(*) FROM vector_chunks v
        WHERE EXISTS (SELECT 1 FROM _canon c WHERE c.doc_id = v.doc_id AND v.bank <> c.canonical)
    """)
    n = cur.fetchone()[0]

    bak = f"vector_chunks_bankfix_bak_{time.strftime('%Y%m%d%H%M')}"
    cur.execute(f"""
        CREATE TABLE {bak} AS
        SELECT v.doc_id, v.chunk_index, v.bank, v.content, v.metadata, v.created_at
        FROM vector_chunks v
        WHERE EXISTS (SELECT 1 FROM _canon c WHERE c.doc_id = v.doc_id AND v.bank <> c.canonical)
    """)
    pg.commit()
    print(f"\n备份表 {bak}: {n} 行")

    cur.execute("""
        DELETE FROM vector_chunks v
        WHERE EXISTS (SELECT 1 FROM _canon c WHERE c.doc_id = v.doc_id AND v.bank <> c.canonical)
    """)
    deleted = cur.rowcount
    pg.commit()
    print(f"已删残留: {deleted} 行")
    pg.close()


if __name__ == "__main__":
    main()
