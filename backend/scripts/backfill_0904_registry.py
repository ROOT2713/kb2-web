#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0904 数据治理 Plan A — 一档回填 + registry 打标（一次性运维脚本，幂等）

出处: kb2 数据治理 0904 会话（交接文件 /home/ubuntu/kb2-data-governance-0904-handoff.md）
定性: 真孤儿 13,711 = 13,706(6月批次 BGE-M3 回填未落 SQLite 元数据) + 5(8月波)
方案: 修订版 A —— 一档回填 + 检索端过滤孤儿 + 防复发
  A. 一档回填: pg 有 title 且 SQLite 无行的 359 个孤儿 → SQLite documents 建行
     (title/bank/hs_bank/category 取自 pg metadata, source='backfill_0904',
      searchable=1, status='active', coverage=1.0 → 进入 BM25 与语义检索)
  B. registry 打标: SQLite documents 全部 doc_id ∩ pg 实存 chunk →
     metadata |= {"registry":"1"}（检索端过滤基准,见 vector_repo.query_by_embedding FIX-0904）
  C. 13,352 个无 title 原子条目不回填不打标 → 检索天然不可见, 数据保留不删

用法:
  python3 backfill_0904_registry.py            # dry-run: 只打印计划与计数
  python3 backfill_0904_registry.py --apply    # 实际写入（幂等,可重复跑）

凭据: DSN 从 backend/.env 读 pgvector_database_url / DB_PATH, 不硬编码。
回滚:
  SQLite: DELETE FROM documents WHERE source='backfill_0904';
  pg:     UPDATE vector_chunks SET metadata = metadata - 'registry' WHERE doc_id = ANY(<原集合>);
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
ENV_PATH = os.path.join(BASE, ".env")

DEFAULT_SQLITE = "/data/projects/kb-web/data/kb.db"
DEFAULT_PG_KEY = "pgvector_database_url"


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


def main():
    ap = argparse.ArgumentParser(description="0904 Plan A: 一档回填 + registry 打标")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"

    cfg = load_env()
    dsn = cfg.get(DEFAULT_PG_KEY, "")
    sqlite_path = cfg.get("DB_PATH", DEFAULT_SQLITE)
    if not dsn:
        print("[FATAL] pgvector_database_url 未在 %s 中找到" % ENV_PATH)
        return 1
    print("== 0904 Plan A 一档回填+打标 [%s] ==" % mode)
    print("  sqlite: %s" % sqlite_path)
    print("  pg:     %s (host 省略凭据)" % dsn.split("@")[-1])

    import psycopg2
    import sqlite3

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    sdb = sqlite3.connect(sqlite_path)
    scur = sdb.cursor()

    # ── 0) 读两库现状 ─────────────────────────────
    cur.execute(
        "SELECT DISTINCT doc_id FROM vector_chunks "
        "WHERE metadata->>'title' IS NOT NULL AND metadata->>'title' <> ''"
    )
    pg_titled = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT doc_id FROM vector_chunks")
    pg_all = {r[0] for r in cur.fetchall()}
    cur.execute(
        "SELECT DISTINCT doc_id FROM vector_chunks WHERE metadata->>'registry' = '1'"
    )
    pg_registered = {r[0] for r in cur.fetchall()}
    sqlite_ids = {r[0] for r in scur.execute("SELECT doc_id FROM documents").fetchall()}

    print("  pg doc 总数: %d | 有 title: %d | 已打标 registry: %d" % (
        len(pg_all), len(pg_titled), len(pg_registered)))
    print("  sqlite documents: %d" % len(sqlite_ids))

    # ── A) 一档回填候选: pg 有 title ∩ sqlite 无行 ──
    candidates = pg_titled - sqlite_ids
    print("  [A] 回填候选(pg有title∩sqlite无行): %d" % len(candidates))

    # bank 映射: hs_bank → legacy bank（语义对照, 非多数票——kb_general 下 4 行 kb_xhs
    # 是历史遗留脏映射, 多数票会被误导; 参考 retrieval.py BANKS/LEGACY_BANK_TO_HS 口径）
    HS_TO_LEGACY = {
        "kb_standard": "standards",
        "kb_industry": "industry",
        "kb_xhs": "咨询",
        "kb_general": "general",
    }
    hs_to_legacy = HS_TO_LEGACY
    print("  hs_bank→legacy bank 映射(语义对照): %s" % json.dumps(hs_to_legacy, ensure_ascii=False))

    rows_to_insert = []
    if candidates:
        cur.execute(
            "SELECT doc_id, bank, min(created_at) "
            "FROM vector_chunks WHERE doc_id = ANY(%s) GROUP BY doc_id, bank",
            (list(candidates),),
        )
        doc_bank_created = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        # 每个 doc 取最小 chunk_index 的 title（title 可能不在 chunk0）
        cur.execute(
            "SELECT DISTINCT ON (doc_id) doc_id, metadata->>'title', metadata->>'category', metadata->>'concept_id' "
            "FROM vector_chunks WHERE doc_id = ANY(%s) AND metadata->>'title' IS NOT NULL "
            "AND metadata->>'title' <> '' ORDER BY doc_id, chunk_index",
            (list(candidates),),
        )
        for doc_id, title, category, concept_id in cur.fetchall():
            hs_bank, created_at = doc_bank_created.get(doc_id, ("kb_general", None))
            legacy = hs_to_legacy.get(hs_bank, "general")
            rows_to_insert.append({
                "doc_id": doc_id, "title": (title or "")[:500],
                "category": category or "", "concept_id": concept_id or "",
                "bank": legacy, "hs_bank": hs_bank,
                "created_at": created_at,
            })
    # 补 chunk_count（pg 侧每 doc chunk 数）
    if rows_to_insert:
        cur.execute(
            "SELECT doc_id, count(*) FROM vector_chunks WHERE doc_id = ANY(%s) GROUP BY doc_id",
            ([r["doc_id"] for r in rows_to_insert],),
        )
        cc = {r[0]: r[1] for r in cur.fetchall()}
        for r in rows_to_insert:
            r["chunk_count"] = cc.get(r["doc_id"], 0)

    # ── 校验(回填前) ─────────────────────────────
    orphan_no_title = pg_all - sqlite_ids - pg_titled
    print("  [C] 不回填不打标(无title孤儿, 检索不可见, 数据保留): %d" % len(orphan_no_title))
    unbackfilled_titled = pg_titled - sqlite_ids - set(r["doc_id"] for r in rows_to_insert)
    print("  [C] 校验: 有title但未入回填计划: %d (应为0)" % len(unbackfilled_titled))

    if mode == "DRY-RUN":
        print("\n[dry-run] 将插入 %d 行 documents（样例前3）:" % len(rows_to_insert))
        for r in rows_to_insert[:3]:
            print("   ", json.dumps({k: (str(v)[:60]) for k, v in r.items()}, ensure_ascii=False))
        # 打标集合预测(当前 sqlite ∩ pg 实存; apply 后新回填行并入)
        tag_ids_preview = sqlite_ids & pg_all
        print("[dry-run] 将打标 registry=1: 当前 sqlite∩pg=%d 个 doc; "
              "apply 后新回填 %d 行并入 sqlite, 打标集合动态重算(含回填)" % (
                  len(tag_ids_preview), len(rows_to_insert)))
        print("[dry-run] 未执行任何写入。加 --apply 实际执行。")
        return 0

    # ── APPLY ────────────────────────────────────
    n_ins = 0
    if rows_to_insert:
        for r in rows_to_insert:
            scur.execute(
                "INSERT OR IGNORE INTO documents "
                "(doc_id, title, category, bank, hs_bank, source, doc_type, searchable, status, "
                " coverage_pct, chunk_count, created_at, updated_at, content_hash, concept_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["doc_id"], r["title"], r["category"], r["bank"], r["hs_bank"],
                 "backfill_0904", "generic", 1, "active", 1.0, r["chunk_count"],
                 r["created_at"] or "2026-06-01T00:00:00+00:00", "2026-09-04T00:00:00+00:00",
                 "", r["concept_id"] or None),
            )
            n_ins += scur.rowcount if scur.rowcount and scur.rowcount > 0 else 0
        sdb.commit()
    print("[apply] SQLite 新增 documents 行: %d" % n_ins)

    # 打标（jsonb concat, 幂等）——集合须在回填 INSERT 后动态重算(最新 sqlite 全量 ∩ pg 实存),
    # 否则新回填行漏标 → 检索端过滤会误杀刚回填文档。
    sqlite_ids_final = {r[0] for r in scur.execute("SELECT doc_id FROM documents").fetchall()}
    cur.execute("SELECT DISTINCT doc_id FROM vector_chunks")
    pg_all_final = {r[0] for r in cur.fetchall()}
    tag_ids = sqlite_ids_final & pg_all_final
    print("  [B] 打标集合(回填后 sqlite∩pg实存): %d" % len(tag_ids))
    if tag_ids:
        cur.execute(
            "UPDATE vector_chunks SET metadata = COALESCE(metadata, '{}'::jsonb) || '{\"registry\":\"1\"}'::jsonb "
            "WHERE doc_id = ANY(%s)",
            (list(tag_ids),),
        )
        conn.commit()
    print("[apply] pg 打标 doc 数: %d (UPDATE rowcount=%s)" % (len(tag_ids), cur.rowcount))

    # 校验输出
    sqlite_now = scur.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    cur.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM vector_chunks WHERE metadata->>'registry' = '1'"
    )
    tagged_now = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM vector_chunks "
        "WHERE COALESCE(metadata->>'registry','') <> '1' AND "
        "COALESCE(metadata->>'title','') = ''"
    )
    orphan_still = cur.fetchone()[0]
    # 防漏标自检: 回填后 sqlite 全量 ∩ pg 实存 应全部打标
    miss = (sqlite_ids_final & pg_all_final) - tag_ids
    if miss:
        print("[verify][WARN] sqlite∩pg 存在未打标 doc %d 个: %s" % (len(miss), list(miss)[:5]))
    else:
        print("[verify] sqlite∩pg 全部已打标 (无遗漏)")
    print("[verify] sqlite documents: %d (期望 %d)" % (sqlite_now, len(sqlite_ids) + n_ins))
    print("[verify] pg 已打标 doc: %d" % tagged_now)
    print("[verify] 仍未打标且无title(应≈13,352 孤儿): %d" % orphan_still)

    conn.close()
    sdb.close()
    print("完成。重启服务后 registry 过滤生效；BM25 索引重建后回填 doc 进入关键词检索。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
