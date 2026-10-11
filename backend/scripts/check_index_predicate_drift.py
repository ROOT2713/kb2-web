#!/usr/bin/env python3
"""部分索引谓词漂移巡检 —— 只读，零副作用（watchdog 语义）。

┌─ 为什么需要它（README 未修项 B）───────────────────────────────┐
│ 检索主路径依赖 5 个「bank + registry 双谓词内嵌」部分 HNSW 索引： │
│   idx_vc_kb_{standard,industry,xhs,general,project}_pr          │
│ 其谓词必须与代码检索 WHERE 严格对齐：                            │
│   vector_repo.py: bank=$1 AND embedding IS NOT NULL             │
│                  AND metadata->>'registry'='1'                  │
│ 一旦任一侧漂移（改代码没改索引 / 改索引没改代码 / registry 值   │
│ 变更 / 新增 bank 无索引），pgvector 会**静默退回全量索引** ——    │
│ 不报错、不告警，只是召回悄悄缩水（与未修项 A 同一失效类）。      │
│ 本脚本把「漂移」变成 CI 可拦截的硬失败。                        │
└────────────────────────────────────────────────────────────────┘

额外发现（本脚本会检查）：这 5 个部分索引**不在仓库任何脚本/迁移中**，
是 2026-10-07 手工 CREATE 的 ⇒ 库从 create_pgvector_tables.py 重建时
它们会静默消失。配套 `create_partial_vector_indexes.py` 补上 DDL 来源。

用法：
    python3 check_index_predicate_drift.py            # 连库巡检（默认）
    python3 check_index_predicate_drift.py --verbose   # 附 INFO（含陈旧索引/DDL 提示）
    python3 check_index_predicate_drift.py --offline-snapshot snap.json   # 离线（CI 无 DB）
    python3 check_index_predicate_drift.py --strict    # WARN 也判失败

退出码：0 = 一致（watchdog 静默）；1 = 检出漂移/覆盖缺口；2 = 巡检本身失败（连不上库等）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

# ── 承重点：与生产代码同步 ─────────────────────────────────────────
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SQL_FILE = os.path.join(REPO_ROOT, "backend", "app", "repositories", "vector_repo.py")
ENV_FILE = os.path.join(REPO_ROOT, "backend", ".env")
TABLE = "vector_chunks"

# 严重度 → 是否判失败（WARN 仅在 --strict 下判失败）
FAIL_SEVERITIES = {"CRITICAL", "ALERT"}

# 代码谓词签名提取（顺带覆盖 registry key/value 与 bank 过滤列）
_RE_CODE_REGISTRY = re.compile(
    r"metadata\s*->>\s*'(?P<key>[^']+)'\s*=\s*'(?P<val>[^']+)'"
)
_RE_CODE_BANK = re.compile(r"\bbank\s*=\s*\$\d+")

# 索引谓词提取（indexdef 形如 ((bank = 'kb_general'::text) AND ((metadata ->> 'registry'::text) = '1'::text))）
_RE_IDX_NAME = re.compile(
    r"CREATE\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\S+)", re.I
)
_RE_IDX_BANK = re.compile(r"\bbank\s*=\s*'(?P<bank>[^']+)'")
_RE_IDX_REGISTRY = re.compile(
    r"metadata\s*->>\s*'(?P<key>[^']+)'\s*(?:::text)?\s*\)?\s*=\s*'(?P<val>[^']+)'"
)


@dataclass
class Problem:
    severity: str
    subject: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.subject}: {self.reason}"


# ── 纯函数（无 IO，可离线单测）──────────────────────────────────────
def extract_code_predicate(sql_source: str) -> dict:
    """从 vector_repo.py 源码提取检索 WHERE 的谓词签名。"""
    m = _RE_CODE_REGISTRY.search(sql_source or "")
    return {
        "registry_key": m.group("key") if m else None,
        "registry_value": m.group("val") if m else None,
        "bank_filter": _RE_CODE_BANK.search(sql_source or "") is not None,
    }


def parse_index_def(indexdef: str) -> dict:
    """从 pg_indexes.indexdef 解析单个部分索引的谓词签名。"""
    n = _RE_IDX_NAME.search(indexdef or "")
    b = _RE_IDX_BANK.search(indexdef or "")
    r = _RE_IDX_REGISTRY.search(indexdef or "")
    return {
        "name": n.group("name") if n else "",
        "bank": b.group("bank") if b else None,
        "registry_key": r.group("key") if r else None,
        "registry_value": r.group("val") if r else None,
    }


def check_drift(
    code: dict,
    indexes: list[dict],
    banks_with_data: dict[str, int],
    ddl_declared: bool,
) -> list[Problem]:
    """比对代码谓词 × 索引谓词 × 数据分布，返回漂移问题清单（空 = 一致）。"""
    problems: list[Problem] = []

    # E1 代码缺 bank 过滤 ⇒ 所有部分索引不可用
    if not code.get("bank_filter"):
        problems.append(Problem(
            "CRITICAL", "code",
            "检索 WHERE 缺 `bank = $N` ⇒ 全部部分索引不可用（退回全量索引，静默丢召回）",
        ))

    # E2 索引 registry 谓词与代码不一致 ⇒ 该索引静默失效
    for idx in indexes:
        if not idx.get("bank") or not idx.get("registry_key"):
            problems.append(Problem(
                "CRITICAL", idx.get("name") or "<unnamed>",
                "索引谓词缺 bank 或 registry（非预期的部分索引）",
            ))
            continue
        if code.get("bank_filter") and (
            idx["registry_key"] != code.get("registry_key")
            or idx["registry_value"] != code.get("registry_value")
        ):
            problems.append(Problem(
                "CRITICAL", idx["name"],
                "registry 谓词漂移：索引 "
                f"{idx['registry_key']}={idx['registry_value']} vs 代码 "
                f"{code.get('registry_key')}={code.get('registry_value')}",
            ))

    # E3 有数据但无匹配部分索引的 bank ⇒ 该 bank 静默退化
    covered = {i["bank"] for i in indexes if i.get("bank")}
    for bank, cnt in sorted(banks_with_data.items()):
        if bank not in covered:
            problems.append(Problem(
                "ALERT", bank,
                f"{cnt} 行 registry=1 数据无部分索引 ⇒ 该 bank 静默退化（走全量索引，召回可能缩水）",
            ))

    # E4 陈旧索引（bank 在数据中已不存在）—— 无害，仅 INFO
    for bank in sorted(covered):
        if bank not in banks_with_data:
            problems.append(Problem(
                "INFO", bank,
                "部分索引对应的 bank 在当前数据中不存在（陈旧索引，无害但占空间）",
            ))

    # E5 部分索引无 DDL 来源 ⇒ 库重建即静默消失
    if indexes and not ddl_declared:
        problems.append(Problem(
            "WARN", "ddl",
            "部分索引不在仓库任何脚本/迁移中 ⇒ 库重建后静默消失（补齐 DDL 来源）",
        ))

    return problems


# ── IO 层 ──────────────────────────────────────────────────────────
def _read_env_dsn() -> str:
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line.lower().startswith("pgvector_database_url="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"[FATAL] 未在 {ENV_FILE} 找到 pgvector_database_url")


def _psql(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(
        ["psql", dsn, "-tA", "-F", "\x1f", "-c", sql],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()[:300]}")
    return [ln.split("\x1f") for ln in r.stdout.splitlines() if ln.strip()]


def fetch_index_defs(dsn: str) -> list[dict]:
    rows = _psql(dsn, (
        f"SELECT indexname, indexdef FROM pg_indexes "
        f"WHERE tablename='{TABLE}' AND indexdef LIKE '%WHERE%';"
    ))
    return [parse_index_def(r[1]) for r in rows]


def fetch_banks_with_data(dsn: str) -> dict[str, int]:
    rows = _psql(dsn, (
        f"SELECT bank, count(*) FROM {TABLE} "
        f"WHERE embedding IS NOT NULL AND metadata->>'registry'='1' "
        f"GROUP BY bank ORDER BY 2 DESC;"
    ))
    return {r[0]: int(r[1]) for r in rows}


def ddl_declares_partial_indexes(index_names: list[str]) -> bool:
    """仓库是否有**DDL 来源**声明这些部分索引（逐名核对）。

    只扫合法 DDL 目录（backend/scripts、backend/migrations、scripts、*.sql），
    显式排除 tests/ 与 docs/ —— 否则测试文件里的 "CREATE INDEX" 字样会造成假阳性
    （2026-10-12 实测踩到：backend/tests 里的断言字符串把本检查蒙过去了）。
    """
    if not index_names:
        return True
    wanted = set(index_names)
    found: set[str] = set()
    for path in _ddl_source_files(REPO_ROOT):
        if os.path.abspath(path) == os.path.abspath(__file__):
            continue  # 本文件（含正则/样例）不算 DDL 来源
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "CREATE INDEX" not in src.upper():
            continue
        found |= {n for n in wanted if n in src}
    return found >= wanted


def _ddl_source_files(repo_root: str):
    """枚举合法 DDL 来源文件（排除 tests/docs/产物目录）。"""
    for rel in ("backend/scripts", "backend/migrations", "scripts"):
        base = os.path.join(repo_root, rel)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", "node_modules", "tests", "docs"}]
            for fn in files:
                if fn.endswith((".py", ".sql", ".sh")):
                    yield os.path.join(root, fn)


def load_snapshot(path: str) -> tuple[list[dict], dict[str, int]]:
    data = json.load(open(path, encoding="utf-8"))
    idx = [parse_index_def(d) if isinstance(d, str) else d for d in data["indexes"]]
    return idx, data["banks_with_data"]


def main() -> int:
    ap = argparse.ArgumentParser(description="pgvector 部分索引谓词漂移巡检（只读）")
    ap.add_argument("--verbose", action="store_true", help="打印 INFO 级明细")
    ap.add_argument("--strict", action="store_true", help="WARN 也判失败")
    ap.add_argument("--offline-snapshot", help="离线快照 JSON（CI 无 DB 时用）")
    ap.add_argument("--dump-snapshot", help="把当前库的索引/数据分布写入快照 JSON 后退出")
    args = ap.parse_args()

    try:
        code = extract_code_predicate(open(SQL_FILE, encoding="utf-8").read())
        if args.offline_snapshot:
            indexes, banks = load_snapshot(args.offline_snapshot)
        else:
            dsn = _read_env_dsn()
            indexes, banks = fetch_index_defs(dsn), fetch_banks_with_data(dsn)
    except Exception as e:  # 巡检自身失败 ≠ 检出漂移
        print(f"⚠️  巡检无法完成：{e}", file=sys.stderr)
        return 2

    if args.dump_snapshot:
        raw = _psql(_read_env_dsn(), (
            f"SELECT indexdef FROM pg_indexes "
            f"WHERE tablename='{TABLE}' AND indexdef LIKE '%WHERE%' ORDER BY indexname;"
        ))
        os.makedirs(os.path.dirname(os.path.abspath(args.dump_snapshot)), exist_ok=True)
        with open(args.dump_snapshot, "w", encoding="utf-8") as f:
            json.dump({"indexes": [r[0] for r in raw], "banks_with_data": banks},
                      f, ensure_ascii=False, indent=2)
        print(f"快照已写入 {args.dump_snapshot}（{len(raw)} 索引 / {len(banks)} bank）")
        return 0

    ddl_ok = ddl_declares_partial_indexes([i["name"] for i in indexes])
    problems = check_drift(code, indexes, banks, ddl_ok)

    if args.verbose:
        print(f"代码谓词: registry={code['registry_key']}={code['registry_value']} "
              f"bank_filter={code['bank_filter']}")
        for i in indexes:
            print(f"  索引 {i['name']}: bank={i['bank']} "
                  f"registry={i['registry_key']}={i['registry_value']}")
        print(f"有数据 bank（registry=1）: {banks}")
        print(f"DDL 已声明: {ddl_ok}")

    fail_sev = set(FAIL_SEVERITIES) | ({"WARN"} if args.strict else set())
    fatal = [p for p in problems if p.severity in fail_sev]

    if not args.verbose and not fatal:
        show = []
    else:
        show = [p for p in problems if p.severity != "INFO" or args.verbose]

    if not fatal and not show:
        return 0  # 一致 → 静默（watchdog 语义）

    if show:
        print("🚨 pgvector 部分索引谓词漂移巡检")
        for p in show:
            print(f"   {p}")
    if fatal:
        print("\n排查：代码谓词见 vector_repo.py 检索 WHERE；索引谓词见 "
              "`SELECT indexdef FROM pg_indexes WHERE tablename='vector_chunks'`；"
              "重建索引见 backend/scripts/create_partial_vector_indexes.py。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
