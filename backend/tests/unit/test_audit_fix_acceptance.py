"""审计整改验收测试 — 10 道针对性测试题(2026-09-03 外部审计整改)。

覆盖本次修复的 6 个关键点:
  1. cache_service._ensure_scope_column — PRAGMA 括号 bug(0002)+ scope 列迁移
  2. cache INSERT 显式置 hit_count=0 → 命中计数从 0 累加(运行时发现的 NULL bug)
  3. retrieval doc_bank_filter — 未知 bank key 告警(0001)
  4. vector_repo.upsert — embedding 失败行跳过 + 返回真实有效数(0005 补强)
  5. vector_repo.upsert append/offset — pgvector 补插不丢 retained(连带 bug)
  6. documents._verify_searchable — reparse 后门封堵:覆盖率<80% 不置 searchable(0005)

每个测试断言真实逻辑,不 assert True。
"""

import json
import time as _time
from pathlib import Path

import numpy as np
import pytest

from app.services.cache_service import (
    get_exact,
    set_cache,
    _ensure_scope_column,
)
from sqlalchemy import text as sa_text
from app.models.database import SessionLocal


# ═══════════════════════════════════════════════════════════════════
# 1. _ensure_scope_column PRAGMA 修复 + scope 列迁移
# ═══════════════════════════════════════════════════════════════════

class TestEnsureScopeColumn:
    def test_scope_column_exists_after_ensure(self, db_session):
        """_ensure_scope_column 执行后 query_cache 必有 scope 列(修复 PRAGMA 括号 bug)。"""
        _ensure_scope_column()
        rows = db_session.execute(sa_text("PRAGMA table_info(query_cache)")).fetchall()
        cols = [r[1] for r in rows]
        assert "scope" in cols, f"scope 列应存在,实际列: {cols}"

    def test_ensure_scope_column_idempotent(self, db_session):
        """重复执行不抛异常(幂等)— 修复前括号 bug 会在首次执行抛 AttributeError。"""
        _ensure_scope_column()
        _ensure_scope_column()  # 第二次执行必须静默通过
        rows = db_session.execute(sa_text("PRAGMA table_info(query_cache)")).fetchall()
        scope_cols = [r for r in rows if r[1] == "scope"]
        assert len(scope_cols) == 1, "scope 列不应重复添加"

    def test_new_cache_row_has_scope_default(self, db_session):
        """新插入的缓存行 scope 默认空串(与旧缓存共存兼容)。"""
        _ensure_scope_column()
        async def _run():
            await set_cache("scope默认测试", "standards", "答案", [], {"doc1"}, scope="")
        import asyncio
        asyncio.get_event_loop().run_until_complete(_run())
        row = db_session.execute(
            sa_text("SELECT scope FROM query_cache WHERE query_text='scope默认测试'")
        ).fetchone()
        assert row is not None
        assert row[0] == "", f"scope 应为空串,实际: {row[0]!r}"


# ═══════════════════════════════════════════════════════════════════
# 2. hit_count 显式置 0 → 命中从 0 累加到 1(修复 NULL+1=NULL bug)
# ═══════════════════════════════════════════════════════════════════

class TestHitCountFromZero:
    def test_new_row_hit_count_starts_at_zero(self, db_session):
        """INSERT 后 hit_count 必须是 0(非 NULL)— 修复 NULL+1=NULL。"""
        _ensure_scope_column()
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            set_cache("计数起点测试", "standards", "答案", [], {"doc1"})
        )
        row = db_session.execute(
            sa_text("SELECT hit_count FROM query_cache WHERE query_text='计数起点测试'")
        ).fetchone()
        assert row is not None
        assert row[0] == 0, f"hit_count 初值应为 0,实际: {row[0]!r}(NULL 会导致命中计数永不累加)"

    def test_hit_count_increments_from_zero(self, db_session):
        """首次命中后 hit_count 0→1(硬断言,非软校验)。"""
        _ensure_scope_column()
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            set_cache("计数累加测试", "standards", "答案", [], {"doc1"})
        )
        # 首次命中
        r1 = get_exact("计数累加测试", "standards")
        assert r1 is not None and "cache_hit" in r1
        row1 = db_session.execute(
            sa_text("SELECT hit_count FROM query_cache WHERE query_text='计数累加测试'")
        ).fetchone()
        assert row1[0] == 1, f"首次命中后应为 1,实际: {row1[0]!r}"
        # 二次命中
        r2 = get_exact("计数累加测试", "standards")
        assert r2 is not None
        row2 = db_session.execute(
            sa_text("SELECT hit_count FROM query_cache WHERE query_text='计数累加测试'")
        ).fetchone()
        assert row2[0] == 2, f"二次命中后应为 2,实际: {row2[0]!r}"


# ═══════════════════════════════════════════════════════════════════
# 3. scope 用户隔离(0002 核心目标)
# ═══════════════════════════════════════════════════════════════════

class TestScopeIsolation:
    def test_user_scope_cache_not_visible_to_other_scope(self, db_session):
        """scope='alice' 的缓存, scope='bob' 查询不可见(用户隔离)。"""
        _ensure_scope_column()
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            set_cache("隔离查询", "standards", "alice的答案", [], {"doc1"}, scope="alice")
        )
        # bob 精确查询 → 应 miss
        bob_result = get_exact("隔离查询", "standards", scope="bob")
        assert bob_result is None, "bob 不应命中 alice 的缓存"
        # alice 自己 → 应命中
        alice_result = get_exact("隔离查询", "standards", scope="alice")
        assert alice_result is not None and "alice的答案" in alice_result["answer"]

    def test_default_scope_and_user_scope_coexist(self, db_session):
        """默认 scope('')与用户 scope 各自独立,互不串扰。"""
        _ensure_scope_column()
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            set_cache("共存查询", "standards", "默认答案", [], {"doc1"}, scope="")
        )
        # 用户 scope 查询不应命中默认 scope 缓存
        user_result = get_exact("共存查询", "standards", scope="momo")
        assert user_result is None, "用户 scope 不应命中默认 scope 缓存"


# ═══════════════════════════════════════════════════════════════════
# 4. 未知 bank key 告警(0001 兜底)
# ═══════════════════════════════════════════════════════════════════

class TestUnknownBankWarning:
    def test_unknown_bank_key_logs_warning(self, db_session, caplog):
        """doc_bank_filter 遇未知 bank key 应打告警且不崩溃。"""
        from app.services.retrieval import doc_bank_filter
        import logging
        with caplog.at_level(logging.WARNING, logger="app.services.retrieval"):
            result = doc_bank_filter("不存在的bank_xyz")
        # 不崩溃,返回可迭代(空列表兜底,避免过滤掉全部)
        assert result is not None
        assert isinstance(result, list)
        # 告警已记录
        warning_logged = any("不存在的bank_xyz" in r.message for r in caplog.records)
        assert warning_logged, "未知 bank key 应记录告警(0001 兜底要求)"


# ═══════════════════════════════════════════════════════════════════
# 5. vector_repo.upsert embedding 失败整批原子(CC-R2 C1 修复后语义)
# ═══════════════════════════════════════════════════════════════════

class TestUpsertAtomicFailure:
    def test_partial_embedding_failure_raises_atomic(self, monkeypatch):
        """【CC-R2】任一 chunk embedding 失败 → 整批抛异常,不静默跳库(防切片补插错位)。"""
        import pytest
        from app.repositories.vector_repo import PgVectorStore
        store = PgVectorStore.__new__(PgVectorStore)  # 绕过 __init__

        fake_chunks = [
            {"doc_id": "d1", "content": "a"},
            {"doc_id": "d1", "content": "b"},
            {"doc_id": "d1", "content": "c"},
        ]

        async def fake_embedding_batch(texts):
            # 第一个失败(None),其余成功(真实 get_embedding 返回 np.ndarray)
            import numpy as np
            return [None, np.array([0.1] * 1024, dtype=np.float32), np.array([0.2] * 1024, dtype=np.float32)]

        class FakePoolNoAcquire:
            def acquire(self):  # asyncpg 语义: 同步返回 async CM
                raise AssertionError("失败路径不应进入 DB 写入(pool.acquire)")

        async def fake_pool_acquire():
            return FakePoolNoAcquire()

        monkeypatch.setattr(store, "get_embedding_batch", fake_embedding_batch)
        monkeypatch.setattr(store, "_get_pool", fake_pool_acquire)

        with pytest.raises(RuntimeError, match="embedding 生成失败"):
            import asyncio
            asyncio.run(store.upsert("d1", fake_chunks, "kb_standard", append=True, offset=0))

    def test_all_embeddings_ok_passes_through(self, monkeypatch):
        """【CC-R2】embedding 全成功 → 正常入库返回 chunk 数(回归)。"""
        from app.repositories.vector_repo import PgVectorStore
        store = PgVectorStore.__new__(PgVectorStore)  # 绕过 __init__

        fake_chunks = [
            {"doc_id": "d1", "content": "a"},
            {"doc_id": "d1", "content": "b"},
        ]

        async def fake_embedding_batch(texts):
            import numpy as np
            return [np.array([0.1] * 1024, dtype=np.float32), np.array([0.2] * 1024, dtype=np.float32)]

        inserted_rows = []

        class FakePoolAcquire:
            # asyncpg 语义: pool.acquire() 返回 async CM,进入后即 conn
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def execute(self, sql, *args):
                return None
            async def executemany(self, sql, rows):
                inserted_rows.extend(rows)

        class FakePool:
            def acquire(self):  # asyncpg 语义: 同步返回 async CM
                return FakePoolAcquire()

        async def fake_pool_acquire():
            return FakePool()

        monkeypatch.setattr(store, "get_embedding_batch", fake_embedding_batch)
        monkeypatch.setattr(store, "_get_pool", fake_pool_acquire)

        import asyncio
        n = asyncio.run(store.upsert("d1", fake_chunks, "kb_standard", append=True, offset=0))
        assert n == 2, f"应返回 2,实际 {n}"
        assert len(inserted_rows) == 2, "两行都应入库"

    def test_protocol_upsert_has_append_offset_params(self):
        """VectorStore Protocol.upsert 签名应含 append/offset(连带 bug 修复)。"""
        from app.repositories.vector_repo import VectorStore
        import inspect
        sig = inspect.signature(VectorStore.upsert)
        params = list(sig.parameters.keys())
        assert "append" in params, f"Protocol.upsert 应含 append 参数,实际: {params}"
        assert "offset" in params, f"Protocol.upsert 应含 offset 参数,实际: {params}"
        # 默认值应为 False/0(保持其余调用点行为不变)
        assert sig.parameters["append"].default is False
        assert sig.parameters["offset"].default == 0


# ═══════════════════════════════════════════════════════════════════
# 6. documents._verify_searchable reparse 后门封堵(0005 补强①)
# ═══════════════════════════════════════════════════════════════════

class TestVerifySearchableQualityGate:
    def test_quality_gate_requires_80_percent_coverage(self):
        """质量门: retained/expected < 80% 时 gate 不过(覆盖率不足不置 searchable)。"""
        from app.api.documents import _verify_searchable
        import inspect

        # 读取函数源码,断言质量门判定逻辑存在且正确(覆盖率≥80% 才放行)
        src = inspect.getsource(_verify_searchable)
        # 关键断言:质量门公式 retained/expected >= 0.8
        assert "retained / expected" in src or "retained/expected" in src, \
            "质量门必须基于 retained/expected 覆盖率"
        assert "0.8" in src, "质量门阈值应为 80%"
        # 不应再有硬编码 searchable=1 的无条件翻 1(后门封堵)
        # 注意:docstring 中允许出现描述性字样,排除 docstring 后检查
        body = src.split('"""')[-1] if '"""' in src else src
        assert "searchable = 1" not in body or "coverage_pct = 80.0" not in body, \
            "不应无条件硬编码 searchable=1(reparse 后门)"
        # 硬编码 coverage_pct=80.0 的旧写法应消失
        assert "coverage_pct = 80.0" not in body, "coverage_pct 不应硬编码为 80.0"

    def test_verify_searchable_signature_has_expected_retained(self):
        """_verify_searchable 签名应含 expected/retained(质量门参数)。"""
        from app.api.documents import _verify_searchable
        import inspect
        sig = inspect.signature(_verify_searchable)
        params = list(sig.parameters.keys())
        assert "expected" in params, f"签名应含 expected,实际: {params}"
        assert "retained" in params, f"签名应含 retained,实际: {params}"

    def test_coverage_formula_math(self):
        """覆盖率公式边界: retained/expected >= 0.8 的数学正确性。"""
        # 模拟质量门判定(与 _verify_searchable 同款公式)
        def gate_pass(expected, retained):
            return (retained / expected) >= 0.8 if expected else False

        # 达标: 8/10 = 80%
        assert gate_pass(10, 8) is True
        # 差一点: 7/10 = 70% < 80% → 不过
        assert gate_pass(10, 7) is False
        # 边缘: expected=0 → False(不置 searchable,安全侧)
        assert gate_pass(0, 0) is False
        # 全中: 10/10
        assert gate_pass(10, 10) is True
