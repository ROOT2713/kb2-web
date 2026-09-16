#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 孤儿向量清理（一次性运维脚本，可逆）

出处: kb2 数据治理 0904 会话 P2 阶段
背景: v1 时代 backfill_bgem3 把 memory_units 记忆体转储为 vector_chunks,
      其 doc_id 在 SQLite documents 无记录 → 检索不可见(D3/registry 双重过滤),
      但占 vector_chunks 40.7% 行数 / ~150MB。
安全性: ① 内容 15,529/15,531 在 memory_units 有同文本(源,不动)
        ② 无任何外键引用 vector_chunks
        ③ retrieval 已过滤, 删除不改变检索结果
        ④ 备份表保留 doc_id/bank/chunk_index/content/metadata(不含 embedding, 可由
           content + bge-m3 重算)

用法:
    python3 p2_purge_orphans.py                # dry-run: 统计 + 抽样
    python3 p2_purge_orphans.py --apply        # 建备份表 + 分批删除
    python3 p2_purge_orphans.py --apply --reindex   # 追加 REINDEX + VACUUM
    python3 p2_purge_orphans.py --rollback     # 从备份表恢复
"""
import argparse
import os
import sys
import time

ENV = "/home/ubuntu/kb2-web/backend/.env"
SQLITE_DB = "/home/ubuntu/kb-web/data/kb.db"
BAK_TABLE = "vector_chunks_orphan_bak_20260916"
BATCH = 2000


def dsn() -> str:
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            if line.startswith("pgvector_database_url"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("未找到 pgvector_database_url")


def sqlite_doc_ids() -> set:
    import sqlite3
    con = sqlite3.connect(f"file:{SQLITE_DB}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("SELECT doc_id FROM documents")}
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    import psycopg2
    pg = psycopg2.connect(dsn())
    pg.autocommit = False
    cur = pg.cursor()

    if args.rollback:
        print("=== 回滚：从备份表恢复 ===")
        cur.execute("SELECT to_regclass(%s)", (BAK_TABLE,))
        if not cur.fetchone()[0]:
            raise SystemExit(f"备份表 {BAK_TABLE} 不存在，无法回滚")
        cur.execute(f"SELECT COUNT(*) FROM {BAK_TABLE}")
        n = cur.fetchone()[0]
        print(f"   备份表行数: {n}")
        cur.execute(
            f"INSERT INTO vector_chunks (doc_id, chunk_index, bank, content, metadata, created_at) "
            f"SELECT doc_id, chunk_index, bank, content, metadata, created_at FROM {BAK_TABLE} "
            f"ON CONFLICT DO NOTHING")
        print(f"   已回插 {cur.rowcount} 行（embedding 为 NULL，需重算）")
        pg.commit()
        print("   回滚完成")
        return

    print("=== ① 目标集合统计 ===")
    ids = sqlite_doc_ids()
    cur.execute("SELECT COUNT(*) FROM vector_chunks")
    total = cur.fetchone()[0]

    cur.execute("CREATE TEMP TABLE _keep (doc_id text primary key)")
    if ids:
        cur.executemany("INSERT INTO _keep VALUES (%s)", [(d,) for d in ids])

    # 待删集合 = 不在 SQLite documents 且 metadata->>'registry' != '1'
    # （registry=1 的是显式可见行，单独决策，不混入本次清理）
    ORPH_WHERE = """NOT EXISTS (SELECT 1 FROM _keep k WHERE k.doc_id = v.doc_id)
                    AND COALESCE(v.metadata->>'registry','') <> '1'"""
    cur.execute(f"SELECT COUNT(*) FROM vector_chunks v WHERE {ORPH_WHERE}")
    orphan_n = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(DISTINCT v.doc_id) FROM vector_chunks v WHERE {ORPH_WHERE}")
    orphan_docs = cur.fetchone()[0]

    print(f"   SQLite documents doc_id:      {len(ids)}")
    print(f"   vector_chunks 总行数:         {total}")
    print(f"   孤儿行数（待删）:             {orphan_n}  ({orphan_n*100.0/total:.1f}%)")
    print(f"   孤儿 doc_id 数:               {orphan_docs}")
    print(f"   删除后剩余:                   {total - orphan_n}")

    print("\n=== ② registry 校验（待删集合应全部无 registry=1）===")
    cur.execute(f"""SELECT COALESCE(metadata->>'registry','<无>') r, COUNT(*)
                   FROM vector_chunks v WHERE {ORPH_WHERE} GROUP BY r""")
    for r, n in cur.fetchall():
        flag = "  <-- 注意!" if r == "1" else ""
        print(f"   registry={r:<8s} {n:>6}{flag}")

    print("\n=== ②b 被排除的 registry=1 行（单独决策，本次不动）===")
    cur.execute("""SELECT v.doc_id, v.bank, COALESCE(metadata->>'title','') t, COUNT(*)
                   FROM vector_chunks v
                   WHERE COALESCE(v.metadata->>'registry','') = '1'
                     AND NOT EXISTS (SELECT 1 FROM _keep k WHERE k.doc_id = v.doc_id)
                   GROUP BY v.doc_id, v.bank, t""")
    for did, b, t, n in cur.fetchall():
        print(f"   {did[:8]} [{b}] {n} 行  {t[:60]}")

    print("\n=== ③ metadata->>'title' 非空抽样（防误删有名文档）===")
    cur.execute(f"""SELECT v.doc_id, v.bank, metadata->>'title'
                   FROM vector_chunks v WHERE {ORPH_WHERE}
                     AND COALESCE(metadata->>'title','') <> '' LIMIT 10""")
    rows = cur.fetchall()
    if not rows:
        print("   （无：待删集合 title 全为空）")
    for did, b, t in rows:
        print(f"   {did[:8]} [{b}] {t[:70]}")

    print("\n=== ④ 内容源对照（memory_units 是否保有同文本）===")
    cur.execute(f"""SELECT COUNT(*) FROM vector_chunks v WHERE {ORPH_WHERE}
                     AND NOT EXISTS (SELECT 1 FROM memory_units m WHERE m.text = v.content)""")
    lost = cur.fetchone()[0]
    print(f"   待删中内容在 memory_units 找不到同文本的: {lost} / {orphan_n}")
    if lost:
        print("   !! 存在无源内容，需人工确认后再删")

    if not args.apply:
        print("\n[dry-run] 未做任何修改。加 --apply 执行。")
        pg.rollback()
        return

    print("\n=== ⑤ 建备份表 ===")
    cur.execute("SELECT to_regclass(%s)", (BAK_TABLE,))
    if cur.fetchone()[0]:
        cur.execute(f"SELECT COUNT(*) FROM {BAK_TABLE}")
        print(f"   备份表已存在，行数 {cur.fetchone()[0]}（跳过建表）")
    else:
        cur.execute(f"""CREATE TABLE {BAK_TABLE} AS
                        SELECT doc_id, chunk_index, bank, content, metadata, created_at
                        FROM vector_chunks v WHERE {ORPH_WHERE}""")
        cur.execute(f"SELECT COUNT(*) FROM {BAK_TABLE}")
        print(f"   备份表 {BAK_TABLE} 建好，行数 {cur.fetchone()[0]}（不含 embedding，可重算）")
    pg.commit()

    print("\n=== ⑥ 分批删除 ===")
    done = 0
    t0 = time.time()
    while True:
        cur.execute(f"""DELETE FROM vector_chunks WHERE ctid IN (
                          SELECT v.ctid FROM vector_chunks v WHERE {ORPH_WHERE}
                          LIMIT {BATCH})""")
        n = cur.rowcount
        pg.commit()
        done += n
        if n == 0:
            break
        print(f"     已删 {done} / {orphan_n}  ({time.time()-t0:.0f}s)")
    print(f"   删除完成: {done} 行，耗时 {time.time()-t0:.0f}s")

    print("\n=== ⑦ 删除后核验 ===")
    cur.execute("SELECT COUNT(*) FROM vector_chunks")
    after = cur.fetchone()[0]
    cur.execute(f"""SELECT COUNT(*) FROM vector_chunks v WHERE {ORPH_WHERE}""")
    left = cur.fetchone()[0]
    print(f"   剩余总行数:     {after}  (期望 {total - orphan_n})")
    print(f"   剩余孤儿:       {left}  (期望 0)")
    print(f"   备份表行数:     ", end="")
    cur.execute(f"SELECT COUNT(*) FROM {BAK_TABLE}")
    print(cur.fetchone()[0])

    if args.reindex:
        print("\n=== ⑧ REINDEX + VACUUM ===")
        t1 = time.time()
        print("   REINDEX idx_vc_embedding ...")
        cur.execute("REINDEX INDEX idx_vc_embedding")
        pg.commit()
        print(f"   完成 ({time.time()-t1:.0f}s)")
        print("   VACUUM ...")
        pg.autocommit = True
        cur.execute("VACUUM")
        print(f"   VACUUM 完成 (总 {time.time()-t1:.0f}s)")

    cur.execute("SELECT pg_size_pretty(pg_total_relation_size('vector_chunks'))")
    print(f"\n   vector_chunks 表大小: {cur.fetchone()[0]}")
    pg.close()
    print("\n完成。回滚用 --rollback")


if __name__ == "__main__":
    sys.exit(main())
