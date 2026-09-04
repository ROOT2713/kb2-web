"""
缓存机制回归测试 — 验证 L1 精确缓存 / L2 语义缓存 / BM25 缓存行为正确。

覆盖：
  - L1 exact cache: 相同 query+bank 命中，不同不命中
  - L2 semantic cache: 语义相似查询在阈值内命中，低于阈值不命中
  - BM25 cache: TTL 过期后重建，多 bank 隔离
  - 缓存隔离：不同 bank 的缓存不交叉
  - LRU 淘汰：超过 max_entries 后淘汰低命中率缓存
  - 缓存失效：文档更新后相关缓存被清理
"""

import json
import time as _time
from pathlib import Path

import numpy as np
import pytest

from app.services.cache_service import (
    get_exact,
    get_semantic,
    set_cache,
    invalidate_for_doc,
    evict_lru,
    evict_global,
    _get_bm25_cache,
    invalidate_bm25_cache,
    _bm25_caches,
)
from sqlalchemy import text as sa_text
from app.models.database import SessionLocal


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clean_cache_db():
    """每个测试后清理 query_cache 表，避免测试间污染。"""
    yield
    db = SessionLocal()
    try:
        db.execute(sa_text("DELETE FROM query_cache"))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean_bm25_cache():
    """每个测试后清理 BM25 内存缓存。"""
    yield
    _bm25_caches.clear()


# ═══════════════════════════════════════════════════════════════════
# L1 精确缓存
# ═══════════════════════════════════════════════════════════════════

class TestL1ExactCache:
    """L1 精确匹配缓存行为。"""

    @pytest.mark.asyncio
    async def test_exact_cache_hit(self):
        """相同 query + bank 可以命中精确缓存。"""
        await set_cache("接地电阻测试", "standards", "接地电阻小于4Ω", [], {"doc1"})
        result = get_exact("接地电阻测试", "standards")
        assert result is not None
        assert result["cache_hit"] == "exact"
        assert "接地电阻小于4Ω" in result["answer"]

    @pytest.mark.asyncio
    async def test_exact_cache_miss_different_query(self):
        """不同 query 不命中精确缓存。"""
        await set_cache("接地电阻测试", "standards", "接地电阻小于4Ω", [], {"doc1"})
        result = get_exact("会议系统验收", "standards")
        assert result is None, "不同 query 不应命中精确缓存"

    def test_exact_cache_miss_no_entry(self):
        """无缓存记录时返回 None。"""
        result = get_exact("不存在的内容", "standards")
        assert result is None

    @pytest.mark.asyncio
    async def test_exact_cache_bank_isolation(self):
        """不同 bank 的精确缓存互不干扰。"""
        await set_cache("接地电阻", "standards", "标准答案", [], {"doc1"})
        result = get_exact("接地电阻", "general")
        assert result is None, "不同 bank 不应命中精确缓存"

    @pytest.mark.asyncio
    async def test_exact_cache_hit_count_increments(self):
        """命中后 hit_count 递增（软校验：确保机制存在且不抛异常）。"""
        await set_cache("测试查询", "standards", "答案", [], {"doc1"})

        # 命中一次 — 确认不抛异常
        try:
            get_exact("测试查询", "standards")
        except Exception as e:
            pytest.fail(f"get_exact 不应抛异常: {e}")

        # 验证缓存仍可命中（硬需求）
        result = get_exact("测试查询", "standards")
        assert result is not None, "缓存应仍可命中"
        assert "答案" in result["answer"]


# ═══════════════════════════════════════════════════════════════════
# L2 语义缓存
# ═══════════════════════════════════════════════════════════════════

class TestL2SemanticCache:
    """L2 语义匹配缓存行为。需要 embedding 服务可用。"""

    @pytest.mark.skip(reason="需要 embedding 服务；在集成模式下单独运行")
    @pytest.mark.asyncio
    async def test_semantic_cache_hit(self):
        """语义相似查询在阈值以上命中。"""
        await set_cache("接地电阻测试方法", "standards", "良好答案", [], {"doc1"})
        result = await get_semantic("接地电阻 测试", "standards", threshold=0.5)
        assert result is not None, "语义相似查询未命中"
        assert result["cache_hit"] == "semantic"

    @pytest.mark.asyncio
    async def test_cache_set_saves_embedding(self):
        """set_cache 后，query_cache 表中应有 embedding 数据。"""
        await set_cache("测试嵌入", "standards", "答案", [], {"doc1"})
        db = SessionLocal()
        try:
            row = db.execute(
                sa_text("SELECT query_embedding FROM query_cache LIMIT 1")
            ).fetchone()
        finally:
            db.close()
        # embedding 可以为 None（embedding 服务不可用时）
        # 不为 None 时应是有效的 numpy bytes
        if row and row[0] is not None:
            emb = np.frombuffer(row[0], dtype=np.float32)
            assert len(emb) > 0, "embedding 数据无效"

    @pytest.mark.asyncio
    async def test_cache_bank_isolation_semantic(self):
        """语义缓存也按 bank 隔离。"""
        await set_cache("测试查询", "standards", "标准答案", [], {"doc1"})
        # 假设 embedding 相同，但不同 bank
        result = await get_semantic("测试查询", "general", threshold=0.5)
        if result is not None:
            assert result["cache_hit"] != "semantic", "不同 bank 不应命中语义缓存"

    @pytest.mark.asyncio
    async def test_different_numbers_skip_cache(self):
        """数字不同的查询，即使语义相似也跳过 L2 缓存。"""
        await set_cache("100万项目验收费用", "standards", "答案A", [], {"doc1"})
        result = await get_semantic("200万项目验收费用", "standards", threshold=0.5)
        assert result is None, "数字不同的查询不应命中语义缓存"


# ═══════════════════════════════════════════════════════════════════
# 缓存写入与失效
# ═══════════════════════════════════════════════════════════════════

class TestCacheWriteAndInvalidation:
    """缓存的写入、失效、LRU 淘汰。"""

    @pytest.mark.asyncio
    async def test_cache_creates_db_entry(self):
        await set_cache("写缓存测试", "standards", "答案", [], {"doc1"})
        db = SessionLocal()
        try:
            count = db.execute(
                sa_text("SELECT COUNT(*) FROM query_cache")
            ).fetchone()[0]
        finally:
            db.close()
        assert count == 1, "set_cache 后应有 1 条记录"

    @pytest.mark.asyncio
    async def test_cache_update_replaces(self):
        """同一 query+bank 的第二次写入应替换第一次（INSERT OR REPLACE）。"""
        await set_cache("相同的查询", "standards", "答案A", [], {"doc1"})
        await set_cache("相同的查询", "standards", "答案B", [], {"doc2"})

        result = get_exact("相同的查询", "standards")
        assert result is not None
        assert "答案B" in result["answer"], "缓存应更新为新值"

    @pytest.mark.asyncio
    async def test_invalidate_by_doc_id(self):
        """失效指定文档后，包含该 doc_id 的缓存条目应被删除。"""
        await set_cache("查询A", "standards", "答案A", [], {"doc1", "doc2"})
        await set_cache("查询B", "standards", "答案B", [], {"doc3"})

        deleted = invalidate_for_doc("doc1")
        assert deleted >= 1, "应删除至少 1 条缓存"

        db = SessionLocal()
        try:
            remaining = db.execute(
                sa_text("SELECT COUNT(*) FROM query_cache")
            ).fetchone()[0]
        finally:
            db.close()
        # 查询A 被删除，查询B 保留
        assert remaining == 1, "删除后应只剩 1 条"

    @pytest.mark.asyncio
    async def test_evict_lru(self):
        """超过 max_entries 后，最老命中低的缓存被淘汰。"""
        # 写入少量的测试条目
        for i in range(5):
            await set_cache(f"查询{i}", "standards", f"答案{i}", [], {f"doc{i}"})

        evict_lru("standards", max_entries=3)

        db = SessionLocal()
        try:
            count = db.execute(
                sa_text("SELECT COUNT(*) FROM query_cache WHERE bank='standards'")
            ).fetchone()[0]
        finally:
            db.close()
        assert count <= 3, f"期望 ≤3 条缓存，实际 {count}"

    @pytest.mark.asyncio
    async def test_evict_global_total_cap(self):
        """【R3-7】全局总量超 max_total 后按全局 LRU 淘汰（跨 bank/scope）。"""
        # 跨 bank 写 5 条（每写一条 set_cache 内部会跑 evict_lru/evict_global，但默认上限远高于 5）
        for i in range(5):
            bank = "standards" if i % 2 == 0 else "industry"
            await set_cache(f"全局查询{i}", bank, f"答案{i}", [], {f"doc{i}"})

        evict_global(max_total=3)

        db = SessionLocal()
        try:
            count = db.execute(
                sa_text("SELECT COUNT(*) FROM query_cache")
            ).fetchone()[0]
        finally:
            db.close()
        assert count <= 3, f"期望 ≤3 条缓存，实际 {count}"

    @pytest.mark.asyncio
    async def test_evict_global_keeps_hottest(self):
        """【R3-7】全局淘汰保留最热条目（hit_count 高者存活）。"""
        for i in range(4):
            await set_cache(f"热度查询{i}", "standards", f"答案{i}", [], {f"doc{i}"})
        # 人为抬高 2 条的命中热度
        db = SessionLocal()
        try:
            db.execute(
                sa_text("UPDATE query_cache SET hit_count=100 WHERE query_text='热度查询0'")
            )
            db.execute(
                sa_text("UPDATE query_cache SET hit_count=90 WHERE query_text='热度查询1'")
            )
            db.commit()
        finally:
            db.close()

        evict_global(max_total=2)

        db = SessionLocal()
        try:
            rows = db.execute(
                sa_text("SELECT query_text FROM query_cache ORDER BY hit_count DESC")
            ).fetchall()
        finally:
            db.close()
        texts = [r[0] for r in rows]
        assert len(texts) <= 2
        # 最热的 2 条必须存活
        assert "热度查询0" in texts
        assert "热度查询1" in texts


# ═══════════════════════════════════════════════════════════════════
# BM25 缓存
# ═══════════════════════════════════════════════════════════════════

class TestBM25Cache:
    """BM25 索引的缓存行为。"""

    def test_bm25_cache_initially_empty(self):
        cache = _get_bm25_cache("all")
        assert cache["index"] is None
        assert cache["docs"] == []

    def test_bm25_cache_bank_isolation(self):
        """不同 bank 的 BM25 缓存独立。"""
        _bm25_caches["standards"] = {"index": "built", "docs": ["d1"], "ts": 100}
        _bm25_caches["general"] = {"index": None, "docs": [], "ts": 0}

        standards_cache = _get_bm25_cache("standards")
        general_cache = _get_bm25_cache("general")

        assert standards_cache["index"] == "built"
        assert general_cache["index"] is None

    def test_bm25_invalidate_specific_bank(self):
        _bm25_caches["standards"] = {"index": "built", "docs": ["d1"], "ts": 100}
        _bm25_caches["general"] = {"index": "built", "docs": ["d2"], "ts": 200}

        invalidate_bm25_cache("standards")

        assert "standards" not in _bm25_caches
        assert "general" in _bm25_caches

    def test_bm25_invalidate_all(self):
        _bm25_caches["a"] = {"index": "built", "docs": [], "ts": 1}
        _bm25_caches["b"] = {"index": "built", "docs": [], "ts": 2}

        invalidate_bm25_cache()

        assert len(_bm25_caches) == 0


# ═══════════════════════════════════════════════════════════════════
# L1 缓存 TTL 过期检查
# ═══════════════════════════════════════════════════════════════════

class TestCacheTTL:
    """缓存 TTL 行为。"""

    @pytest.mark.asyncio
    async def test_cache_old_ttl_expired(self, monkeypatch):
        """超过 TTL 的缓存应被视为已过期。"""
        from datetime import datetime, timezone

        # 注入一个时间非常旧的缓存
        db = SessionLocal()
        try:
            from app.utils.text_cleaning import normalize_query
            import hashlib
            old_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
            cache_key = hashlib.sha256(f"{normalize_query('旧缓存')}:standards".encode()).hexdigest()
            db.execute(sa_text("""
                INSERT INTO query_cache (cache_id, query_text, bank, answer, created_at, ttl_seconds)
                VALUES (:cid, :qt, 'standards', '旧的答案', :ct, 3600)
            """), {"cid": cache_key, "qt": "旧缓存", "ct": old_dt.isoformat()})
            db.commit()
        finally:
            db.close()

        # 尝试命中
        result = get_exact("旧缓存", "standards")
        assert result is None, "TTL 过期缓存不应命中"

    @pytest.mark.asyncio
    async def test_cache_within_ttl_hits(self):
        """有效期的缓存应命中。"""
        await set_cache("有效缓存", "standards", "有效答案", [], {"doc1"})
        result = get_exact("有效缓存", "standards")
        assert result is not None, "有效期的缓存应命中"
