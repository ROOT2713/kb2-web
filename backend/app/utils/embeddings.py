"""Embedding utilities — get query/document embeddings via API.

Ported from: kb-web server.py get_query_embedding() L428-L459
"""

import logging
from typing import List, Optional

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# 内存LRU缓存：query → np.array
_embed_cache: dict = {}


async def get_embedding(text: str) -> Optional[np.ndarray]:
    """获取查询向量（智谱 embedding-2 API），带内存LRU缓存"""
    if not text or not text.strip():
        return None
    api_key = settings.embedding_api_key
    if not api_key:
        return None
    # 内存LRU缓存：避免同一查询重复调用API
    cache_key = text.strip()
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]
    try:
        embed_url = settings.embedding_url or "https://open.bigmodel.cn/api/paas/v4/embeddings"
        model = settings.embedding_model or "embedding-2"
        resp = httpx.post(
            embed_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": cache_key},
            timeout=10,
        )
        data = resp.json()
        vec = np.array(data["data"][0]["embedding"], dtype=np.float32)
        # LRU淘汰：超过500条删除最早的
        if len(_embed_cache) >= 500:
            oldest_key = next(iter(_embed_cache))
            del _embed_cache[oldest_key]
        _embed_cache[cache_key] = vec
        return vec
    except Exception as e:
        logger.warning(f"embedding failed: {e}")
        return None
