"""
Regression test conftest — 错题自动记录 + pytest 选项。

在 pytest session 结束时自动收集所有失败用例，记录到错题库。
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ERRORS_DIR = Path(__file__).resolve().parent / "errors"

# 错题记录文件
_ERRORS_FILE = _ERRORS_DIR / "errors.json"
_HISTORY_FILE = _ERRORS_DIR / "fix-history.json"

# 不记录的测试文件（纯单元测试的失败不应存为"错题"）
_SKIP_PATTERNS = [
    "test_regression_retrieval.py::TestGoldenQueryIntegrity",  # 元数据校验
    "test_data_integrity.py::TestChunkQuality",                # 数据质量 soft check
    "test_cache_mechanisms.py::TestBM25Cache",                 # 缓存行为
]


def _load_errors() -> dict:
    if not _ERRORS_FILE.exists():
        return {"version": 2, "errors": [], "meta": {"created": None, "updated": None}}
    try:
        return json.loads(_ERRORS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 2, "errors": [], "meta": {"created": None, "updated": None}}


def _save_errors(data: dict):
    _ERRORS_DIR.mkdir(parents=True, exist_ok=True)
    data["meta"]["updated"] = datetime.now(timezone.utc).isoformat()
    _ERRORS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _should_record(node_id: str) -> bool:
    """判断是否应记录为错题（跳过纯结构测试）。"""
    for pat in _SKIP_PATTERNS:
        if pat in node_id:
            return False
    return True


def _infer_category(node_id: str) -> str:
    """从测试文件名推断类别。"""
    if "test_regression_retrieval" in node_id:
        return "检索回归"
    if "test_data_integrity" in node_id:
        return "数据完整性"
    if "test_frontend_endpoints" in node_id:
        return "前端合同"
    if "test_cache_mechanisms" in node_id:
        return "缓存机制"
    if "test_golden_query" in node_id.lower():
        return "黄金查询"
    return "其他"


def pytest_sessionfinish(session, exitstatus):
    """Session 结束时自动将失败用例记录为错题。"""
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal is None:
        return

    failures = terminal.stats.get("failed", [])
    if not failures:
        return

    data = _load_errors()
    now = datetime.now(timezone.utc).isoformat()

    for fail in failures:
        node_id = fail.nodeid
        if not _should_record(node_id):
            continue

        category = _infer_category(node_id)

        # 提取查询关键词（从 node_id 的 parametrize 参数中）
        query = node_id.split("[")[-1].rstrip("]") if "[" in node_id else node_id.split("::")[-1]

        # 查找已有错题
        existing = [
            e for e in data["errors"]
            if e.get("test_node") == node_id and not e.get("fixed_at")
        ]

        if existing:
            entry = existing[0]
            entry["regression_count"] = entry.get("regression_count", 1) + 1
            entry["last_seen_at"] = now
            entry["last_fail_longrepr"] = str(fail.longrepr or "")[:200]
        else:
            entry = {
                "id": f"AUTO-{len([e for e in data['errors'] if not e.get('test_node')]) + 1:04d}",
                "test_node": node_id,
                "query": query,
                "category": category,
                "first_seen_at": now,
                "last_seen_at": now,
                "regression_count": 1,
                "fixed_at": None,
                "last_fail_longrepr": str(fail.longrepr or "")[:200],
            }
            data["errors"].append(entry)

    if data["meta"]["created"] is None:
        data["meta"]["created"] = now
    _save_errors(data)

    if failures:
        print(f"\n📝 [错题积累] 已记录 {len(failures)} 条失败用例到 {_ERRORS_FILE}")
        print(f"   查看: python scripts/wrong_answers.py report")
