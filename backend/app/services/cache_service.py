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

logger = logging.getLogger(__name__)

# ── BM25 索引管理（多 bank 独立缓存 + TTL）─────────────────────────
# Phase2: 每个 bank 独立缓存，切换 bank 时无需重建（避免 10-30s 冷启动）
_bm25_caches: dict = {}  # {"all": {"index": BM25, "docs": [...], "ts": float}, "standards": {...}, ...}
_BM25_TTL = 600  # 10分钟缓存（上传后主动清除，无需长TTL）
_BM25_DOC_COUNT_KEY = "doc_count"  # 增量检测：文档数量变化时才重建



def get_exact(query: str, bank: str) -> Optional[Dict]:
    """L1精确匹配"""
    cache_key = hashlib.sha256(f"{normalize_query(query)}:{bank}".encode()).hexdigest()
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


async def get_semantic(query: str, bank: str, threshold: float = 0.82) -> Optional[Dict]:
    """L2语义匹配（需要 get_embedding 可用时才生效）
    [OPT-03] 阈值从 0.90 降到 0.82，提升近义查询命中率"""
    from app.utils.embeddings import get_embedding
    query_emb = await get_embedding(query)
    if query_emb is None:
        return None
    db = SessionLocal()
    try:
        # [P1-3] 严格bank隔离：所有bank统一用bank参数过滤，all只命中all缓存
        rows = db.execute(
            text("SELECT cache_id, query_text, query_embedding, answer, sources_json, created_at, ttl_seconds "
                 "FROM query_cache WHERE bank=:bank AND query_embedding IS NOT NULL"),
            {"bank": bank}
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


async def set_cache(query: str, bank: str, answer: str, sources: list, doc_ids: set):
    """写入缓存（L1精确key + L2 embedding）"""
    from app.utils.embeddings import get_embedding
    cache_key = hashlib.sha256(f"{normalize_query(query)}:{bank}".encode()).hexdigest()
    embedding = await get_embedding(query)
    emb_blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT OR REPLACE INTO query_cache
            (cache_id, query_text, query_embedding, bank, answer, sources_json, created_at, doc_ids_json)
            VALUES (:cache_id, :query_text, :query_embedding, :bank, :answer, :sources_json, :created_at, :doc_ids_json)
        """), {
            "cache_id": cache_key, "query_text": query, "query_embedding": emb_blob,
            "bank": bank, "answer": answer, "sources_json": json.dumps(sources),
            "created_at": datetime.now(timezone.utc).isoformat(),  # [P2-4]
            "doc_ids_json": json.dumps(list(doc_ids))
        })
        db.commit()
    finally:
        db.close()
    # LRU淘汰
    try:
        evict_lru(bank, max_entries=200)  # [P2-2] reduce LRU max entries
    except Exception:
        pass


def invalidate_for_doc(doc_id: str):
    """文档删除/更新时失效相关缓存"""
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT cache_id, doc_ids_json FROM query_cache")).fetchall()
        count = 0
        for r in rows:
            if doc_id in json.loads(r[1] or "[]"):
                db.execute(text("DELETE FROM query_cache WHERE cache_id=:cache_id"), {"cache_id": r[0]})
                count += 1
        db.commit()
    finally:
        db.close()
    return count


def evict_lru(bank: str, max_entries: int = 1000):
    """LRU淘汰：每个bank最多max_entries条"""
    db = SessionLocal()
    try:
        count = db.execute(
            text("SELECT COUNT(*) FROM query_cache WHERE bank=:bank"), {"bank": bank}
        ).fetchone()[0]
        if count > max_entries:
            db.execute(text("""
                DELETE FROM query_cache WHERE cache_id IN (
                    SELECT cache_id FROM query_cache WHERE bank=:bank
                    ORDER BY hit_count ASC, last_hit_at ASC
                    LIMIT :limit
                )
            """), {"bank": bank, "limit": count - max_entries})
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
