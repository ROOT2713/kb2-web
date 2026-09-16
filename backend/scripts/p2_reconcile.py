#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 数据对账（常态巡检，只读优先）

出处: kb2 数据治理 0904 会话 P2 阶段（机制化防复发）
背景: 孤儿向量（pg 有 / SQLite 无）与僵尸文档（SQLite 有 / pg 无）此前无常态
      发现机制 —— 只有一次性 backfill_0904_registry.py。本脚本把对账常态化为
      可定时执行的巡检，并把"发现异常"变成可告警信号。

四类检查:
  ① 孤儿向量    pg vector_chunks 有 doc_id，SQLite documents 无
                → 检索不可见但占空间（历史上来自 memory_units 转储 / bank 换动残留）
  ② 僵尸文档    SQLite status='active' AND searchable=1，但 pg 无向量
                → 前台可见却检索不到（比孤儿更危险）
  ③ bank 残留   同一 doc_id 在 pg 存在 >1 个 bank
                → FIX-P2-G1 前的产物，删除时只清单 bank 会漏
  ④ 撤销残留    SQLite status='superseded'，但 pg 仍有向量
                → D2 撤销未清干净的残留

用法:
    python3 p2_reconcile.py                        # 全量报告（人工看）
    python3 p2_reconcile.py --quiet                # 无异常则无输出（供 cron/告警）
    python3 p2_reconcile.py --apply-orphans        # 清孤儿：建备份表 + 分批删
    python3 p2_reconcile.py --apply-orphans --orphan-min-age-days 1
                                                   # 只清存在 >=1 天的孤儿（TTL）
    python3 p2_reconcile.py --json                 # 机器可读

退出码:
    0  无异常（--quiet 模式下也用于"有报告已输出"）
    1  发现异常（非 --quiet 模式，供 CI / 人工判断）

安全:
    - 默认全只读；只在显式 --apply-orphans 时才写，且先建带时间戳备份表
    - 待清集合排除 metadata->>'registry'='1'（显式可见行不混入）
    - SQLite 路径自动探测（documents 表行数最多者），打印 inode 便于核验
"""
import argparse
import json
import os
import sqlite3
import sys
import time

ENV = "/home/ubuntu/kb2-web/backend/.env"
SQLITE_CANDIDATES = [
    "/home/ubuntu/kb-web/data/kb.db",
    "/home/ubuntu/kb2-web/backend/data/kb.db",
    "/data/projects/kb-web/data/kb.db",
]
BATCH = 2000


# ── 连接 ────────────────────────────────────────────────────────
def dsn() -> str:
    """从 .env 读 pgvector DSN。"""
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            if line.startswith("pgvector_database_url"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("未找到 pgvector_database_url")


def pick_sqlite() -> str:
    """自动探测含 documents 表的活跃库（取 documents 行数最多者）。

    历史坑: .env 的 DB_PATH 与进程实写路径可能不同 —— 不能盲信单一来源。
    这里按"哪张库真的装着 documents"选，并打印 inode 供人工核验。
    """
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
        raise SystemExit(f"未找到含 documents 表的库，候选: {SQLITE_CANDIDATES}")
    return best


def load_sqlite(path: str):
    """返回 (docs: {doc_id: {status, searchable, bank, hs_bank}}, 表内总行数)。"""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        docs = {}
        for r in con.execute(
            "SELECT doc_id, status, searchable, bank, hs_bank FROM documents"
        ):
            docs[r[0]] = {
                "status": r[1],
                "searchable": r[2],
                "bank": r[3],
                "hs_bank": r[4],
            }
        return docs
    finally:
        con.close()


# ── 检查 ────────────────────────────────────────────────────────
def check_orphans(cur, sqlite_ids: set):
    """① 孤儿向量：pg 有 doc_id，SQLite documents 无。

    返回 (总行数, doc 数, {doc_id: rows}, 最老 created_at)。
    """
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS _keep (doc_id text primary key)")
    cur.execute("DELETE FROM _keep")
    if sqlite_ids:
        cur.executemany("INSERT INTO _keep VALUES (%s)", [(d,) for d in sqlite_ids])

    cur.execute(
        """
        SELECT v.doc_id, COUNT(*) AS n, MIN(v.created_at) AS oldest
        FROM vector_chunks v
        WHERE NOT EXISTS (SELECT 1 FROM _keep k WHERE k.doc_id = v.doc_id)
        GROUP BY v.doc_id
        """
    )
    rows = cur.fetchall()
    detail = {r[0]: r[1] for r in rows}
    total = sum(detail.values())
    oldest = min((r[2] for r in rows if r[2]), default=None)

    # 其中带 registry=1 的（显式可见行，需单独决策，不自动清）
    cur.execute(
        """
        SELECT COUNT(*) FROM vector_chunks v
        WHERE NOT EXISTS (SELECT 1 FROM _keep k WHERE k.doc_id = v.doc_id)
          AND COALESCE(v.metadata->>'registry','') = '1'
        """
    )
    registry_marked = cur.fetchone()[0]
    return total, len(detail), detail, oldest, registry_marked


def check_zombies(cur, docs: dict):
    """② 僵尸文档：SQLite active & searchable=1，但 pg 无向量。"""
    cur.execute("SELECT DISTINCT doc_id FROM vector_chunks")
    pg_ids = {r[0] for r in cur.fetchall()}
    zombies = [
        d
        for d, i in docs.items()
        if i["status"] == "active" and i["searchable"] == 1 and d not in pg_ids
    ]
    return zombies


def check_bank_residue(cur):
    """③ bank 残留：同一 doc_id 跨多个 bank。"""
    cur.execute(
        """
        SELECT doc_id, array_agg(DISTINCT bank ORDER BY bank) AS banks, COUNT(*)
        FROM vector_chunks
        GROUP BY doc_id
        HAVING COUNT(DISTINCT bank) > 1
        """
    )
    return [(r[0], list(r[1]), r[2]) for r in cur.fetchall()]


def check_superseded_residue(cur, docs: dict):
    """④ 撤销残留：SQLite status='superseded' 但 pg 仍有向量。"""
    sup = {d for d, i in docs.items() if i["status"] == "superseded"}
    if not sup:
        return []
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS _sup (doc_id text primary key)")
    cur.execute("DELETE FROM _sup")
    cur.executemany("INSERT INTO _sup VALUES (%s)", [(d,) for d in sup])
    cur.execute(
        """
        SELECT v.doc_id, COUNT(*) FROM vector_chunks v
        JOIN _sup s ON s.doc_id = v.doc_id
        GROUP BY v.doc_id
        """
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


# ── 清理 ────────────────────────────────────────────────────────
def purge_orphans(pg, cur, min_age_days: float) -> int:
    """建备份表 + 分批删孤儿（排除 registry=1）。返回删除行数。"""
    bak = f"vector_chunks_reconcile_bak_{time.strftime('%Y%m%d%H%M')}"

    age_clause = ""
    params = []
    if min_age_days > 0:
        age_clause = " AND v.created_at < NOW() - (%s || ' days')::interval"
        params.append(str(min_age_days))

    ORPH_WHERE = f"""
        NOT EXISTS (SELECT 1 FROM _keep k WHERE k.doc_id = v.doc_id)
        AND COALESCE(v.metadata->>'registry','') <> '1'
        {age_clause}
    """

    cur.execute(f"SELECT COUNT(*) FROM vector_chunks v WHERE {ORPH_WHERE}", params)
    n = cur.fetchone()[0]
    if n == 0:
        print("   待清孤儿: 0 —— 无需操作")
        return 0

    print(f"   待清孤儿: {n} 行 → 建备份表 {bak}")
    cur.execute(
        f"""
        CREATE TABLE {bak} AS
        SELECT v.doc_id, v.chunk_index, v.bank, v.content, v.metadata, v.created_at
        FROM vector_chunks v WHERE {ORPH_WHERE}
        """,
        params,
    )
    pg.commit()

    deleted = 0
    while True:
        cur.execute(
            f"""
            DELETE FROM vector_chunks v
            WHERE ctid IN (
                SELECT ctid FROM vector_chunks v WHERE {ORPH_WHERE} LIMIT {BATCH}
            )
            """,
            params,
        )
        got = cur.rowcount
        pg.commit()
        if got <= 0:
            break
        deleted += got
        print(f"   已删 {deleted}/{n} ...", end="\r")
    print(f"   删除完成: {deleted} 行  (备份表 {bak} 可回滚)")
    return deleted


# ── 主流程 ──────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="P2 数据对账（pg ↔ SQLite）")
    ap.add_argument("--quiet", action="store_true",
                    help="无异常时无输出（供 cron/告警；有异常则输出报告并以 0 退出）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--apply-orphans", action="store_true",
                    help="清理孤儿向量（建备份表 + 分批删）")
    ap.add_argument("--orphan-min-age-days", type=float, default=0.0,
                    help="孤儿 TTL：只清存在 >=N 天的孤儿（默认 0=全部）")
    args = ap.parse_args()

    import psycopg2

    db_path = pick_sqlite()
    st = os.stat(db_path)
    docs = load_sqlite(db_path)

    pg = psycopg2.connect(dsn())
    pg.autocommit = False
    cur = pg.cursor()

    o_total, o_docs, o_detail, o_oldest, o_registry = check_orphans(cur, set(docs))
    zombies = check_zombies(cur, docs)
    residue = check_bank_residue(cur)
    sup_residue = check_superseded_residue(cur, docs)

    # 计入异常的孤儿 = 无 registry 标记者。
    # registry='1' 的孤儿是"显式可见但无 SQLite 户口"行（历史测试残留），
    # 需人工判断，若计入会导致周检永久误告警（狼来了）→ 降级为 INFO 单列。
    hard_orphans = o_total - o_registry
    anomalies = hard_orphans + len(zombies) + len(residue) + len(sup_residue)

    if args.json:
        print(json.dumps({
            "sqlite_db": db_path,
            "sqlite_inode": st.st_ino,
            "documents": len(docs),
            "active": sum(1 for i in docs.values() if i["status"] == "active"),
            "superseded": sum(1 for i in docs.values() if i["status"] == "superseded"),
            "orphan_rows": o_total,
            "orphan_docs": o_docs,
            "orphan_oldest": o_oldest.isoformat() if o_oldest else None,
            "orphan_registry_marked": o_registry,
            "zombie_docs": len(zombies),
            "zombie_sample": zombies[:10],
            "bank_residue": [{"doc_id": d, "banks": b, "rows": n} for d, b, n in residue],
            "superseded_residue": [{"doc_id": d, "rows": n} for d, n in sup_residue],
            "anomalies": anomalies,
        }, ensure_ascii=False, indent=2))
        if args.apply_orphans and o_total:
            purge_orphans(pg, cur, args.orphan_min_age_days)
        pg.close()
        return

    if args.quiet and anomalies == 0 and not args.apply_orphans:
        pg.close()
        return  # 静默 = 正常

    print("=" * 62)
    print("P2 数据对账报告 (pg vector_chunks ↔ SQLite documents)")
    print("=" * 62)
    print(f"SQLite: {db_path}  inode={st.st_ino}")
    print(f"        documents={len(docs)}  "
          f"active={sum(1 for i in docs.values() if i['status']=='active')}  "
          f"superseded={sum(1 for i in docs.values() if i['status']=='superseded')}")
    cur.execute("SELECT COUNT(*) FROM vector_chunks")
    print(f"pg     vector_chunks={cur.fetchone()[0]} 行")
    print()

    print(f"① 孤儿向量  (pg 有 / SQLite 无)          : {o_total} 行 / {o_docs} doc")
    if o_total:
        print(f"   最老 created_at={o_oldest}")
        print(f"   ├ 无 registry 标记（计入异常）      : {hard_orphans} 行")
        print(f"   └ registry='1'（INFO，需人工判断）  : {o_registry} 行")
        top = sorted(o_detail.items(), key=lambda kv: -kv[1])[:5]
        for d, n in top:
            print(f"     {d[:8]}  {n} 行")
    print(f"② 僵尸文档  (active+searchable=1 / pg 无): {len(zombies)} doc")
    for d in zombies[:10]:
        print(f"     {d[:8]}  {docs[d]['bank']}")
    print(f"③ bank 残留 (同 doc 跨多 bank)           : {len(residue)} doc")
    for d, banks, n in residue[:10]:
        print(f"     {d[:8]}  banks={banks}  {n} 行")
    print(f"④ 撤销残留  (superseded / pg 仍有向量)    : {len(sup_residue)} doc")
    for d, n in sup_residue[:10]:
        print(f"     {d[:8]}  {n} 行")
    print()
    if anomalies == 0:
        print("✅ 无异常 —— 数据面一致")
    else:
        print(f"⚠️  发现 {anomalies} 项异常，见上")
        if args.apply_orphans:
            print("\n--- 清理孤儿 ---")
            purge_orphans(pg, cur, args.orphan_min_age_days)

    pg.close()
    if anomalies and not args.quiet:
        sys.exit(1)


if __name__ == "__main__":
    main()
