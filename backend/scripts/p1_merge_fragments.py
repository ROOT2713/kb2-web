#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 治本 — 碎片归并（一次性运维脚本，幂等）

出处: kb2 数据治理 0904 会话 P1 阶段
背景: backfill_0904 把长文档切成 N 条 doc 记录、每条 1 chunk（碎片）。
      恢复正主（source='p1_recover'）后，同标题的老碎片必须撤销，
      否则碎片向量仍在语义检索中竞争（D2/D3 已修双写与读端过滤）。

本脚本语义（与部署版 version_chain.supersede_and_purge 一致）:
  SQLite: status='superseded', superseded_by=<新 doc>, stale_at=now,
          stale_reason='p1_merge'
  pg:     DELETE FROM vector_chunks WHERE doc_id = ANY(碎片集合)

用法:
  python3 p1_merge_fragments.py                 # dry-run: 只打印计划
  python3 p1_merge_fragments.py --apply         # 实际写入
  python3 p1_merge_fragments.py --apply --title-filter 28448   # 只处理匹配标题

回滚:
  SQLite: UPDATE documents SET status='active', superseded_by=NULL,
          stale_at=NULL, stale_reason=NULL WHERE doc_id = ANY(<碎片集合>);
  pg:     重新上传（向量已删，不可逆）
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
ENV_PATH = os.path.join(BASE, ".env")
DEFAULT_SQLITE = "/data/projects/kb-web/data/kb.db"

FRAG_SOURCE = "backfill_0904"
NEW_SOURCE = "p1_recover"
REASON = "p1_merge"


def load_env():
    cfg = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def build_plan(cur, title_filter=None):
    """返回 [(new_doc_id, new_title, [frag_doc_ids], frag_hs_bank)]"""
    news = cur.execute(
        "SELECT doc_id, title, hs_bank FROM documents "
        "WHERE source=? AND status='active' ORDER BY created_at",
        (NEW_SOURCE,)).fetchall()
    plan = []
    for nid, ntitle, nhs in news:
        t = (ntitle or "").strip()
        if not t:
            continue
        if title_filter and title_filter not in t:
            continue
        frags = cur.execute(
            "SELECT doc_id, hs_bank FROM documents "
            "WHERE title=? AND source=? AND status='active' AND doc_id!=?",
            (t, FRAG_SOURCE, nid)).fetchall()
        if frags:
            ids = [f[0] for f in frags]
            hsb = frags[0][1] or nhs or "kb_standard"
            plan.append((nid, t, ids, hsb))
    return plan


def main():
    ap = argparse.ArgumentParser(description="P1 碎片归并")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    ap.add_argument("--title-filter", default=None, help="只处理标题含该串的组")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"

    cfg = load_env()
    db_path = cfg.get("DB_PATH", DEFAULT_SQLITE)
    dsn = cfg.get("pgvector_database_url", "")

    print(f"== P1 碎片归并 [{mode}] ==")
    print(f"SQLite: {db_path}")
    print(f"pg:     {'<from .env>' if dsn else '<MISSING>'}")

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    plan = build_plan(cur, args.title_filter)

    total_frag = sum(len(p[2]) for p in plan)
    print(f"\n计划: {len(plan)} 组，共 {total_frag} 个碎片待撤销")
    for nid, t, ids, hsb in plan:
        print(f"  {nid[:8]} {t[:56]}")
        print(f"      → 撤销 {len(ids)} 个碎片 [{hsb}]")

    if not args.apply:
        print("\n[DRY-RUN] 未写入。加 --apply 执行。")
        con.close()
        return 0

    # ---- pg 删除 ----
    pg_deleted = {}
    if dsn:
        try:
            import psycopg2
            pg = psycopg2.connect(dsn)
            pc = pg.cursor()
            for nid, t, ids, hsb in plan:
                pc.execute("DELETE FROM vector_chunks WHERE doc_id = ANY(%s)", (ids,))
                pg_deleted[nid] = pc.rowcount
            pg.commit()
            pg.close()
            print(f"\npg: 删除完成 {sum(pg_deleted.values())} 行向量")
        except Exception as e:  # noqa: BLE001
            print(f"\n[WARN] pg 删除失败（继续 SQLite 标记）: {e}")
    else:
        print("\n[WARN] 无 pg DSN，跳过向量清理")

    # ---- SQLite 标记 ----
    now = datetime.now(timezone.utc).isoformat()
    marked = 0
    for nid, t, ids, hsb in plan:
        for fid in ids:
            cur.execute(
                "UPDATE documents SET status='superseded', superseded_by=?, "
                "stale_at=?, stale_reason=? WHERE doc_id=? AND status='active'",
                (nid, now, REASON, fid))
            marked += cur.rowcount
        cur.execute("UPDATE documents SET supersedes=? WHERE doc_id=?", (ids[0], nid))
    con.commit()
    con.close()
    print(f"SQLite: 标记 superseded {marked} 行")
    print("\n完成。验证: SELECT status,COUNT(*) FROM documents "
          "WHERE source='backfill_0904' GROUP BY status;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
