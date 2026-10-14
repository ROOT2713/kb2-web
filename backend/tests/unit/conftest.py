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


# ═══════════════════════════════════════════════════════════════════
# 【FIX-TESTPOLLUTION】单元测试禁止写生产 pg 向量库
#
# 根因（2026-10-14 实测）：
#   test_rejection.py / test_reparse_full_clean_pipeline.py 等用例走**真实上传管线**，
#   其中 documents / parent_chunks 落在**内存 SQLite**（db_session 覆盖 conftest 夹具），
#   而 `PgVectorStore` 是**指向生产 pg 的模块级单例**
#   （`get_vector_store()` → `app.config.settings.pgvector_database_url`）
#   ⇒ 向量写进**生产 pg**、户口写进**测试库** ⇒ 每次跑单测都在生产库留下孤儿向量。
#
# 实测证据：
#   2026-10-12 02:46~06:30 留下 26 条（title=文档A/文档B/重复检测测试文档，各 1 chunk）；
#   2026-10-14 19:01/19:03 两次全量单测又各留 1~2 条 —— 与「跑了几次单测」一一对应。
#
# 修法：只桩「写」方法（upsert / delete）—— 污染源是写；
#       **不桩「读」（query）**，以免改变既有用例语义（部分用例依赖真实召回行为）。
# ═══════════════════════════════════════════════════════════════════

def pytest_configure(config):
    """注册 opt-out marker：需要真实 upsert/delete 实现的用例豁免全局写桩。"""
    config.addinivalue_line(
        "markers",
        "real_vector_store: 本用例直接测 PgVectorStore.upsert/delete 的真实实现，"
        "跳过 _block_vector_writes 全局写桩（这些用例用自建 fake pool，不触生产库）",
    )


@pytest.fixture(autouse=True)
def _block_vector_writes(request, monkeypatch):
    """禁止单元测试向生产 pg 向量库写入（写方法置为空操作，读不动）。

    豁免：标了 `@pytest.mark.real_vector_store` 的用例（它们直接验证 upsert/delete
    的实现细节，用自建 fake pool，不写生产库）。
    """
    if request.node.get_closest_marker("real_vector_store"):
        yield
        return
    from app.repositories import vector_repo

    async def _noop_upsert(self, doc_id, chunks, bank, append=False, offset=0):
        return len(chunks or [])

    async def _noop_delete(self, doc_id, bank):
        return True

    monkeypatch.setattr(vector_repo.PgVectorStore, "upsert", _noop_upsert)
    monkeypatch.setattr(vector_repo.PgVectorStore, "delete", _noop_delete)
    yield
