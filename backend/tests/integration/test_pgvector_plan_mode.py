"""pgvector plan_cache_mode 回归测试（README 未修项 A / 2026-10-12）.

背景（实测复现，单变量 A/B）
---------------------------
检索 SQL（backend/app/repositories/vector_repo.py）形如::

    WITH top_vec AS (
      SELECT ... FROM vector_chunks
      WHERE bank = $1 AND embedding IS NOT NULL AND metadata->>'registry' = '1'
      ORDER BY embedding <=> $2::vector
      LIMIT $3 )
    SELECT ... FROM top_vec ORDER BY score DESC LIMIT $3

部分索引 ``idx_vc_kb_*_pr`` 的谓词 = ``bank = 'kb_x' AND metadata->>'registry' = '1'``。
在 ``force_generic_plan``（真实缓存计划）下 ``$1``(bank) 未知 ⇒ 谓词不可证 ⇒ 用不上
部分索引，退回全量索引 ``idx_vc_embedding`` ⇒ **静默丢召回**（kb_general 实测
custom=10 行 → generic=3 行，3/3 次稳定；psql PREPARE 路径实测曾为 0 行）。

修复：``ALTER DATABASE hindsight SET plan_cache_mode = 'force_custom_plan';``
（不改任何应用代码；手术脚本见 /tmp/surgical_D_plan_cache_mode.md）

注意：``EXPLAIN`` 无法判别 —— 它对该参数化语句强制 custom 规划，两种模式下都显示
部分索引；判别必须看**真实执行行数**（本文件即如此）。

运行::

    pytest backend/tests/integration/test_pgvector_plan_mode.py --run-integration -q
"""

import pytest
import asyncpg

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        "not config.getoption('--run-integration')",
        reason="需要 --run-integration 和真实 pgvector 库",
    ),
]

KNN_SQL = """
WITH top_vec AS (
    SELECT content, metadata, doc_id, chunk_index, embedding
    FROM vector_chunks
    WHERE bank = $1 AND embedding IS NOT NULL AND metadata->>'registry' = '1'
    ORDER BY embedding <=> $2::vector
    LIMIT $3
)
SELECT doc_id, chunk_index FROM top_vec
"""

KNN_LIMIT = 10


def _dsn() -> str:
    from app.config import settings
    return settings.pgvector_database_url


async def _registry_banks(conn) -> list:
    rows = await conn.fetch(
        "SELECT DISTINCT bank FROM vector_chunks "
        "WHERE bank IS NOT NULL AND metadata->>'registry' = '1' ORDER BY bank"
    )
    return [r["bank"] for r in rows]


async def _deterministic_vector(conn, bank: str):
    """确定性取样（ORDER BY doc_id, chunk_index），保证跨运行可复现。"""
    return await conn.fetchval(
        "SELECT embedding::text FROM vector_chunks "
        "WHERE bank = $1 AND embedding IS NOT NULL "
        "ORDER BY doc_id, chunk_index LIMIT 1",
        bank,
    )


async def _knn_rows(conn, bank: str, vec, limit: int = KNN_LIMIT) -> int:
    return len(await conn.fetch(KNN_SQL, bank, vec, limit))


async def test_plan_cache_mode_pinned():
    """数据库级 plan_cache_mode 必须锁定为 force_custom_plan。"""
    conn = await asyncpg.connect(_dsn())
    try:
        mode = await conn.fetchval("SHOW plan_cache_mode")
    finally:
        await conn.close()
    assert mode == "force_custom_plan", (
        f"plan_cache_mode 期望 force_custom_plan，实际 {mode!r}。"
        "该设置可能被库重建/备份还原抹掉 —— 重跑 "
        "ALTER DATABASE hindsight SET plan_cache_mode='force_custom_plan';"
    )


async def test_knn_returns_full_limit_each_bank():
    """锁定模式下，每个 bank 的真实 KNN 必须返回满额行数（部分索引命中）。"""
    conn = await asyncpg.connect(_dsn())
    try:
        banks = await _registry_banks(conn)
        assert banks, "vector_chunks 中不存在 registry='1' 的数据，无法验证"
        short = {}
        for bank in banks:
            vec = await _deterministic_vector(conn, bank)
            if not vec:
                continue
            n = await _knn_rows(conn, bank, vec)
            if n < KNN_LIMIT:
                short[bank] = n
        assert not short, (
            f"以下 bank 的 KNN 未返回满额 {KNN_LIMIT} 行（部分索引未命中，"
            f"疑似退回全量索引）: {short}"
        )
    finally:
        await conn.close()


async def test_generic_plan_degrades_recall():
    """风险证明：generic 计划下至少一个 bank 的召回行数 < custom 计划。

    这是 pgvector/PostgreSQL 已知限制（generic 计划无法证明部分索引谓词）。
    若本用例转红（generic 与 custom 行数完全相同），说明该限制已消除，
    可复核并考虑解除 ALTER DATABASE 锁定。
    """
    conn = await asyncpg.connect(_dsn())
    try:
        banks = await _registry_banks(conn)
        assert banks, "vector_chunks 中不存在 registry='1' 的数据"
        degraded = {}
        for bank in banks:
            vec = await _deterministic_vector(conn, bank)
            if not vec:
                continue
            await conn.execute("SET plan_cache_mode = 'force_custom_plan'")
            rc = await _knn_rows(conn, bank, vec)
            await conn.execute("SET plan_cache_mode = 'force_generic_plan'")
            rg = await _knn_rows(conn, bank, vec)
            if rg < rc:
                degraded[bank] = (rc, rg)
        assert degraded, (
            "generic 与 custom 计划行数完全相同 —— 未观测到降级。"
            "pgvector 可能已修复部分索引谓词限制，可复核并解除 plan_cache_mode 锁定。"
        )
    finally:
        await conn.close()
