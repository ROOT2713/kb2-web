"""Embedding utilities — get query/document embeddings via API.

Ported from: kb-web server.py get_query_embedding() L428-L459

【FIX-005】可靠性改造：
- 同步 httpx.post → httpx.AsyncClient（不再阻塞事件循环）
- 增加 2 次重试（指数退避），失败不再静默——连续失败计日志
- 连续 5 次失败触发 60s 熔断（快速失败防 API 故障时雪崩）
"""

import asyncio
import logging
import time
from typing import Optional

import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# 内存LRU缓存：query → np.array
_embed_cache: dict = {}

# 【FIX-005】简易熔断状态：连续失败次数 ≥ 5 → 60s 内直接返回 None
_EMBED_BREAKER_FAIL_THRESHOLD = 5
_EMBED_BREAKER_COOLDOWN_S = 60.0
_embed_breaker = {"failures": 0, "open_until": 0.0}

_EMBED_ATTEMPTS = 3  # 1 次原始请求 + 2 次重试
_EMBED_TIMEOUT_S = 10


async def get_embedding(text: str) -> Optional[np.ndarray]:
    """获取查询向量（智谱 embedding-2 API），带内存LRU缓存

    失败语义与旧版一致（返回 None，L2 语义缓存静默降级），
    但重试 + 熔断 + 错误日志升级为 error 级，不再无声丢失。
    """
    if not text or not text.strip():
        return None
    api_key = settings.embedding_api_key
    if not api_key:
        return None

    # 内存LRU缓存：避免同一查询重复调用API
    cache_key = text.strip()
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]

    # 【FIX-005】熔断检查
    if _embed_breaker["failures"] >= _EMBED_BREAKER_FAIL_THRESHOLD and \
            time.monotonic() < _embed_breaker["open_until"]:
        return None

    embed_url = settings.embedding_url or "https://open.bigmodel.cn/api/paas/v4/embeddings"
    model = settings.embedding_model or "embedding-2"
    last_err: Optional[Exception] = None

    for attempt in range(_EMBED_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT_S) as client:
                resp = await client.post(
                    embed_url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "input": cache_key},
                )
            data = resp.json()
            vec = np.array(data["data"][0]["embedding"], dtype=np.float32)
            # LRU淘汰：超过500条删除最早的
            if len(_embed_cache) >= 500:
                oldest_key = next(iter(_embed_cache))
                del _embed_cache[oldest_key]
            _embed_cache[cache_key] = vec
            _embed_breaker["failures"] = 0  # 成功即复位
            return vec
        except Exception as e:  # noqa: BLE001 — 网络层/解析层异常统一重试
            last_err = e
            logger.warning("embedding failed (attempt %d/%d): %s", attempt + 1, _EMBED_ATTEMPTS, e)
            if attempt < _EMBED_ATTEMPTS - 1:
                await asyncio.sleep(0.5 * (attempt + 1))  # 退避 0.5s / 1.0s

    # 【FIX-005】全部失败：计数并触发熔断
    _embed_breaker["failures"] += 1
    if _embed_breaker["failures"] >= _EMBED_BREAKER_FAIL_THRESHOLD:
        _embed_breaker["open_until"] = time.monotonic() + _EMBED_BREAKER_COOLDOWN_S
        logger.error(
            "embedding breaker OPENED after %d consecutive failures, cooldown %.0fs (last error: %s)",
            _embed_breaker["failures"], _EMBED_BREAKER_COOLDOWN_S, last_err,
        )
    else:
        logger.error("embedding failed after %d attempts: %s", _EMBED_ATTEMPTS, last_err)
    return None
