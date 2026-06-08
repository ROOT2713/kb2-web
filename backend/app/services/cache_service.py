"""Query cache service — L1 exact + L2 semantic cache.

Ported from: kb-web server.py cache_get_exact() L322-L346,
             cache_get_semantic() L348-L396, cache_set() L460-L480,
             invalidate_cache_for_doc() L482-L495, cache_evict_lru() L497-L513
"""

from typing import Optional, Dict, Any


def get_exact(query: str, bank: str) -> Optional[Dict]:
    """L1 cache: exact query string match."""
    # TODO: Port cache_get_exact()
    raise NotImplementedError


def get_semantic(query: str, bank: str, threshold: float = 0.82) -> Optional[Dict]:
    """L2 cache: semantic similarity match via embedding cosine similarity."""
    # TODO: Port cache_get_semantic()
    raise NotImplementedError


def set_cache(query: str, bank: str, answer: str, sources: list, doc_ids: set):
    """Write query result to cache."""
    # TODO: Port cache_set()
    raise NotImplementedError


def invalidate_for_doc(doc_id: str):
    """Invalidate all cache entries referencing a document."""
    # TODO: Port invalidate_cache_for_doc()
    raise NotImplementedError


def evict_lru(bank: str, max_entries: int = 1000):
    """Evict least-recently-used cache entries."""
    # TODO: Port cache_evict_lru()
    raise NotImplementedError


def warmup_caches():
    """Warm up caches on startup (e.g. BM25 index)."""
    # TODO: Port _warmup_bm25()
    pass
