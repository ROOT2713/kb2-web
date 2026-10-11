#!/usr/bin/env python3
"""创建 vector_chunks 的「bank + registry 双谓词内嵌」部分 HNSW 索引（手工运行）。

┌─ 为什么存在 ─────────────────────────────────────────────────────┐
│ 这 5 个部分索引原先**只存在于数据库**（2026-10-07 手工 CREATE），  │
│ 仓库无 DDL 来源 ⇒ 一旦从 create_pgvector_tables.py 重建库，它们   │
│ 静默消失，全部 bank 退回全量索引（小 bank 召回缩水，见 README     │
│ 未修项 A/B）。本脚本补上可复现的 DDL 来源。                       │
└────────────────────────────────────────────────────────────────┘

★ 幂等：全部 CREATE INDEX CONCURRENTLY IF NOT EXISTS（零停机；已存在则跳过）。
★ 谓词单一来源：WHERE 子句从 vector_repo.py 的检索谓词**推导**（而非再抄一遍）
  ⇒ 代码改谓词后重跑本脚本即可对齐，不会引入新的漂移。
★ 手工运行（**不**自动执行、不进部署流程）；库重建后才需要跑。

用法：
    python3 create_partial_vector_indexes.py --dry-run   # 只打印 SQL
    python3 create_partial_vector_indexes.py             # 执行
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_index_predicate_drift import (  # noqa: E402
    ENV_FILE, SQL_FILE, extract_code_predicate, parse_index_def, _psql,
)

# 物理库名 → 部分索引名（**字面量**，供巡检逐名核对 DDL 来源；勿改成 f-string）。
# 新增 kb_* 库时在此登记；漏登记会被 check_index_predicate_drift.py 的
# E3（覆盖缺口）与 E5（无 DDL 来源）双重告警拦下。
BANK_INDEX_NAMES = {
    "kb_general": "idx_vc_kb_general_pr",
    "kb_industry": "idx_vc_kb_industry_pr",
    "kb_project": "idx_vc_kb_project_pr",
    "kb_standard": "idx_vc_kb_standard_pr",
    "kb_xhs": "idx_vc_kb_xhs_pr",
}
BANKS = list(BANK_INDEX_NAMES)
HNSW_OPTS = "WITH (m = 24, ef_construction = 200)"


def build_sql(banks: list[str], registry_key: str, registry_value: str) -> list[str]:
    """按代码谓词生成幂等 DDL 列表。"""
    stmts = []
    for bank in banks:
        name = BANK_INDEX_NAMES.get(bank, f"idx_vc_{bank}_pr")
        stmts.append(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON vector_chunks "
            f"USING hnsw (embedding vector_cosine_ops) {HNSW_OPTS} "
            f"WHERE bank = '{bank}' AND metadata->>'{registry_key}' = '{registry_value}';"
        )
    return stmts


def main() -> int:
    ap = argparse.ArgumentParser(description="创建部分 HNSW 索引（幂等，手工）")
    ap.add_argument("--dry-run", action="store_true", help="只打印 SQL，不执行")
    ap.add_argument("--dsn", help="覆盖 DSN（默认读 backend/.env）")
    args = ap.parse_args()

    code = extract_code_predicate(open(SQL_FILE, encoding="utf-8").read())
    if not code.get("bank_filter") or not code.get("registry_key"):
        print(f"[FATAL] 无法从 {SQL_FILE} 提取谓词签名：{code}", file=sys.stderr)
        return 2

    stmts = build_sql(BANKS, code["registry_key"], code["registry_value"])
    print(f"# 谓词来源: vector_repo.py → metadata->>'{code['registry_key']}' = "
          f"'{code['registry_value']}' AND bank = <each>")
    for s in stmts:
        print(s)

    if args.dry_run:
        print("\n# dry-run：未执行。")
        return 0

    dsn = args.dsn
    if not dsn:
        for line in open(ENV_FILE, encoding="utf-8"):
            if line.strip().lower().startswith("pgvector_database_url="):
                dsn = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    if not dsn:
        print("[FATAL] 未找到 DSN（--dsn 或 backend/.env:pgvector_database_url）", file=sys.stderr)
        return 2

    for s in stmts:
        _psql(dsn, s)  # CONCURRENTLY 必须单语句、非事务 —— psql -c 满足
        print(f"OK  {s.split()[5]}")

    # 收尾核验
    rows = _psql(dsn, "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='vector_chunks' AND indexdef LIKE '%WHERE%';")
    names = sorted(parse_index_def(r[1])["name"] for r in rows)
    print(f"\n现存部分索引 {len(names)}: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
