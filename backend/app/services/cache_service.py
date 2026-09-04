"""Query cache service — L1 exact + L2 semantic cache. BM25 index cache management.

Ported from: kb-web server.py cache_get_exact() L322-L346,
             cache_get_semantic() L348-L396, cache_set() L460-L480,
             invalidate_cache_for_doc() L482-L495, cache_evict_lru() L497-L513,
             _get_bm25_cache/_invalidate_bm25_cache/_warmup_bm25 L1341-L1365
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import numpy as np
from sqlalchemy import text

from app.config import settings
from app.models.database import SessionLocal
from app.utils.text_cleaning import normalize_query, _extract_numbers
from app.services.query_decomposer import split_sub_queries

logger = logging.getLogger(__name__)

# 【FIX-R3-7】全局缓存总量上限（条）。evict_lru 按 (bank,scope) 分区防单用户灌满，
# 但 scope×bank 组合数可无限增长 → 全局总量仍需封顶；超限按全局 LRU 淘汰最冷。
_CACHE_MAX_TOTAL = 2000


# ── 【FIX-002】scope 列幂等迁移（存量 SQLite 库）───────────────────
# 新库由 create_all 按模型建表自带 scope；存量库在此补列。表不存在时 PRAGMA
# 返回空列表自动跳过（首次启动 create_all 之前属正常路径）。
# 【FIX-R2-4】fail-closed：迁移失败禁用缓存（宁缺毋串），不再静默退化共享缓存——
# 后者与 FIX-002 自身声明的用户隔离原则矛盾（跨用户串缓存）。
_scope_ready = True  # 默认可用；_ensure_scope_column 失败时置 False


def _ensure_scope_column() -> None:
    global _scope_ready
    try:
        _db = SessionLocal()
        try:
            _rows = _db.execute(text("PRAGMA table_info(query_cache)")).fetchall()
            _cols = {r[1] for r in _rows}
            if _cols and "scope" not in _cols:
                _db.execute(text("ALTER TABLE query_cache ADD COLUMN scope VARCHAR NOT NULL DEFAULT ''"))
                _db.execute(text("CREATE INDEX IF NOT EXISTS ix_query_cache_scope ON query_cache (scope)"))
                _db.commit()
                logger.warning("[FIX-002] query_cache 补建 scope 列完成（缓存用户隔离迁移）")
            _scope_ready = True
        finally:
            _db.close()
    except Exception as _e:  # 【FIX-R2-4】迁移失败 → 禁用缓存而非共享（fail-closed）
        _scope_ready = False
        logger.critical("[FIX-R2-4] scope 列迁移失败，查询缓存已禁用（fail-closed，宁缺毋串）: %s", _e)


_ensure_scope_column()

# ── BM25 索引管理（多 bank 独立缓存 + TTL）─────────────────────────
# Phase2: 每个 bank 独立缓存，切换 bank 时无需重建（避免 10-30s 冷启动）
_bm25_caches: dict = {}  # {"all": {"index": BM25, "docs": [...], "ts": float}, "standards": {...}, ...}
_BM25_TTL = 600  # 10分钟缓存（上传后主动清除，无需长TTL）
_BM25_DOC_COUNT_KEY = "doc_count"  # 增量检测：文档数量变化时才重建



def get_exact(query: str, bank: str, scope: str = "") -> Optional[Dict]:
    """L1精确匹配（scope: 用户隔离维度，【FIX-002】）"""
    if not _scope_ready:  # 【FIX-R2-4】fail-closed：scope 迁移失败 → 缓存不可用返回 miss
        return None
    cache_key = hashlib.sha256(f"{normalize_query(query)}:{bank}:{scope or ''}".encode()).hexdigest()
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT answer, sources_json, created_at, ttl_seconds FROM query_cache WHERE cache_id=:cache_id"),
            {"cache_id": cache_key}
        ).fetchone()
        if row:
            created_str = row[2]  # created_at
            created = datetime.fromisoformat(created_str) if isinstance(created_str, str) else created_str
            if (datetime.now(timezone.utc) - created).total_seconds() < (row[3] or 86400):  # [P2-4]
                db.execute(
                    text("UPDATE query_cache SET hit_count=hit_count+1, last_hit_at=:now WHERE cache_id=:cache_id"),
                    {"now": datetime.now(timezone.utc).isoformat(), "cache_id": cache_key}  # [P2-4]
                )
                db.commit()
                return {"answer": row[0], "sources": json.loads(row[1] or "[]"), "cache_hit": "exact"}
            else:
                db.execute(text("DELETE FROM query_cache WHERE cache_id=:cache_id"), {"cache_id": cache_key})
                db.commit()
    finally:
        db.close()
    return None


async def get_semantic(query: str, bank: str, threshold: float = 0.82, scope: str = "") -> Optional[Dict]:
    """L2语义匹配（需要 get_embedding 可用时才生效）
    [OPT-03] 阈值从 0.90 降到 0.82，提升近义查询命中率
    [FIX-002] scope 用户隔离：语义召回仅在同 scope 缓存池内匹配"""
    if not _scope_ready:  # 【FIX-R2-4】fail-closed
        return None
    from app.utils.embeddings import get_embedding
    query_emb = await get_embedding(query)
    if query_emb is None:
        return None
    db = SessionLocal()
    try:
        # [P1-3] 严格bank隔离：所有bank统一用bank参数过滤，all只命中all缓存
        # [FIX-002] 严格scope隔离：不同用户的语义缓存互不可见
        rows = db.execute(
            text("SELECT cache_id, query_text, query_embedding, answer, sources_json, created_at, ttl_seconds "
                 "FROM query_cache WHERE bank=:bank AND scope=:scope AND query_embedding IS NOT NULL"),
            {"bank": bank, "scope": scope or ""}
        ).fetchall()
        best_match = None
        best_sim = 0.0
        for r in rows:
            cached_emb = np.frombuffer(r[2], dtype=np.float32)  # query_embedding
            norm_q = np.linalg.norm(query_emb)
            norm_c = np.linalg.norm(cached_emb)
            if norm_q == 0 or norm_c == 0:
                continue
            sim = float(np.dot(query_emb, cached_emb) / (norm_q * norm_c))
            created_str = r[5]  # created_at
            created = datetime.fromisoformat(created_str) if isinstance(created_str, str) else created_str
            if (datetime.now(timezone.utc) - created).total_seconds() < (r[6] or 86400):  # [P2-4]
                if sim > best_sim and sim >= threshold:
                    # 数字一致性检查：如果两个查询都含数字且集合不同，跳过L2缓存
                    q_nums = _extract_numbers(query)
                    c_nums = _extract_numbers(r[1] or "")  # query_text
                    if q_nums and c_nums and q_nums != c_nums:
                        continue  # 数字不同，不算缓存命中
                    # 子问题一致性检查：如果当前查询和缓存的查询子问题数不同，跳过
                    q_sub_count = len(split_sub_queries(query))
                    c_sub_count = len(split_sub_queries(r[1] or ""))
                    if q_sub_count != c_sub_count:
                        continue  # 子问题数不同，不算缓存命中
                    best_sim = sim
                    best_match = r
        if best_match:
            db.execute(
                text("UPDATE query_cache SET hit_count=hit_count+1, last_hit_at=:now WHERE cache_id=:cache_id"),
                {"now": datetime.now(timezone.utc).isoformat(), "cache_id": best_match[0]}  # [P2-4]
            )
            db.commit()
            return {"answer": best_match[3], "sources": json.loads(best_match[4] or "[]"),
                    "cache_hit": "semantic", "similarity": round(best_sim, 3)}
    finally:
        db.close()
    return None


async def set_cache(query: str, bank: str, answer: str, sources: list, doc_ids: set, scope: str = ""):
    """写入缓存（L1精确key + L2 embedding；scope 用户隔离【FIX-002】）"""
    if not _scope_ready:  # 【FIX-R2-4】fail-closed：scope 迁移失败 → 不写缓存
        return
    from app.utils.embeddings import get_embedding
    cache_key = hashlib.sha256(f"{normalize_query(query)}:{bank}:{scope or ''}".encode()).hexdigest()
    embedding = await get_embedding(query)
    emb_blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT OR REPLACE INTO query_cache
            (cache_id, query_text, query_embedding, bank, scope, answer, sources_json, created_at, doc_ids_json, hit_count)
            VALUES (:cache_id, :query_text, :query_embedding, :bank, :scope, :answer, :sources_json, :created_at, :doc_ids_json, 0)
        """), {
            "cache_id": cache_key, "query_text": query, "query_embedding": emb_blob,
            "bank": bank, "scope": scope or "", "answer": answer, "sources_json": json.dumps(sources),
            "created_at": datetime.now(timezone.utc).isoformat(),  # [P2-4]
            "doc_ids_json": json.dumps(list(doc_ids))
        })
        db.commit()
    finally:
        db.close()
    # LRU淘汰
    try:
        evict_lru(bank, max_entries=200)  # [P2-2] reduce LRU max entries
        evict_global()  # 【FIX-R3-7】全局总量封顶（默认 _CACHE_MAX_TOTAL=2000）
    except Exception:
        pass


def invalidate_for_doc(doc_id: str):
    """文档删除/更新时失效相关缓存"""
    db = SessionLocal()
    try:
        # 【FIX-R2-15】原全表 SELECT 无 WHERE —— doc_ids_json 为 JSON 数组文本，
        # 无法索引，但可用 LIKE 粗过滤（doc_id 为 uuid hex + '-'，无 % _ 通配符语义），
        # 避免每次全表行传输到 Python 层再 json.loads 逐个判。
        rows = db.execute(
            text("SELECT cache_id, doc_ids_json FROM query_cache WHERE doc_ids_json LIKE :pat"),
            {"pat": f"%{doc_id}%"},
        ).fetchall()
        count = 0
        for r in rows:
            if doc_id in json.loads(r[1] or "[]"):
                db.execute(text("DELETE FROM query_cache WHERE cache_id=:cache_id"), {"cache_id": r[0]})
                count += 1
        db.commit()
    finally:
        db.close()
    return count


def invalidate_query_cache_by_bank(bank: str) -> None:
    """上传/重解析后失效查询缓存（该 bank + 'all' 的答案缓存都基于旧文档集）。
    【FIX-R2-7】原只 invalidate_bm25，query_cache 留存旧答案 → 检索不到新文档。
    删除路径用 invalidate_for_doc（per-doc 精确）；新增/内容变更无 doc_id 可对 → 按 bank 清。
    """
    db = SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM query_cache WHERE bank IN (:b1, :b2)"),
            {"b1": bank, "b2": "all"},
        )
        db.commit()
        logger.info("[CACHE] query_cache invalidated %d rows for bank=%s(+all)", result.rowcount, bank)
    except Exception as e:
        db.rollback()
        logger.warning("[CACHE] invalidate_query_cache_by_bank failed: %s", e)
    finally:
        db.close()


def evict_lru(bank: str, max_entries: int = 1000):
    """LRU淘汰：每个 (bank, scope) 组合最多 max_entries 条。

    【FIX-R2-5】原实现仅按 bank COUNT/DELETE —— 多用户下单个 scope
    （如 admin 高频查询）灌满配额会把其他用户的缓存条目一起驱逐。
    改为窗口函数按 (bank, scope) 分组，每组只保留 hit_count/last_hit_at
    最新的 max_entries 条；未超限的组不受影响（scope 隔离公平）。
    排序 DESC：rn=1 为最热（hit_count 最大），rn>max 尾部即最冷条目
    （CC 审查修正：初版误用 ASC 导致淘汰最热保留最冷，方向相反）。
    """
    db = SessionLocal()
    try:
        db.execute(text("""
            DELETE FROM query_cache WHERE cache_id IN (
                SELECT cache_id FROM (
                    SELECT cache_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY bank, scope
                               ORDER BY hit_count DESC, last_hit_at DESC
                           ) AS rn
                    FROM query_cache WHERE bank = :bank
                ) WHERE rn > :max_entries
            )
        """), {"bank": bank, "max_entries": max_entries})
        db.commit()
    finally:
        db.close()


def evict_global(max_total: int = _CACHE_MAX_TOTAL):
    """【FIX-R3-7】全局总量上限：query_cache 总行数超 max_total 时按全局 LRU
    （hit_count DESC, last_hit_at DESC）淘汰最冷条目。
    与 evict_lru 的 (bank,scope) 分区公平互补——分区上限防单用户灌满某组，
    全局上限防 scope×bank 组合无限增长致总量失控。NULL last_hit_at
    （从未命中）在 SQLite DESC 排序中排尾部 → 最优先淘汰，符合 LRU 语义。
    """
    db = SessionLocal()
    try:
        db.execute(text("""
            DELETE FROM query_cache WHERE cache_id IN (
                SELECT cache_id FROM (
                    SELECT cache_id,
                           ROW_NUMBER() OVER (
                               ORDER BY hit_count DESC, last_hit_at DESC
                           ) AS rn
                    FROM query_cache
                ) WHERE rn > :max_total
            )
        """), {"max_total": max_total})
        db.commit()
    finally:
        db.close()


def _get_bm25_cache(bank: str) -> dict:
    """获取指定 bank 的 BM25 缓存，不存在则返回空壳"""
    return _bm25_caches.get(bank, {"index": None, "docs": [], "ts": 0, "doc_count": 0})



def invalidate_bm25_cache(bank: str = None):
    """清除 BM25 缓存。bank=None 清除全部，指定 bank 只清除该 bank"""
    if bank:
        _bm25_caches.pop(bank, None)
        logger.info("BM25 cache cleared for bank=%s", bank)
    else:
        _bm25_caches.clear()
        logger.info("BM25 cache cleared (all banks)")


async def warmup_bm25():
    """启动时预热 BM25 索引（all bank），避免首次查询冷启动"""
    # Lazy import to avoid circular dependency (retrieval imports from cache_service)
    from app.services.retrieval import build_bm25_index
    try:
        import time as _t
        start = _t.time()
        await build_bm25_index(bank="all")
        elapsed = _t.time() - start
        cache = _get_bm25_cache("all")
        logger.info("BM25 warmup done: %d docs in %.1fs", len(cache["docs"]), elapsed)
    except Exception as e:
        logger.warning("BM25 warmup failed (will lazy-load): %s", e)


async def clear_all_cache():
    """清除所有查询缓存（L1+L2 query_cache + BM25 缓存）"""
    count = 0
    db = SessionLocal()
    try:
        result = db.execute(text("DELETE FROM query_cache"))
        count = result.rowcount
        db.commit()
        logger.info("[CACHE] Cleared %d query_cache entries", count)
    except Exception as e:
        db.rollback()
        logger.warning("[CACHE] Clear failed: %s", e)
    finally:
        db.close()
    invalidate_bm25_cache(None)
    return count
