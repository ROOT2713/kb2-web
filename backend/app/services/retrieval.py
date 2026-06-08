"""Retrieval service — Dense + BM25 + RRF merge + Rerank.

Ported from: kb-web server.py query() L3043-L3692, build_bm25_index() L1425-L1528,
             rrf_merge() L1550-L1653
"""

from typing import List, Dict, Any


class RetrievalResult:
    def __init__(self, doc_id: str, chunk_text: str, score: float, source: str = ""):
        self.doc_id = doc_id
        self.chunk_text = chunk_text
        self.score = score
        self.source = source


async def dense_retrieve(query: str, bank: str, top_k: int = 20) -> List[RetrievalResult]:
    """Dense vector retrieval via Hindsight."""
    # TODO: Port from kb-web server.py query() dense path
    raise NotImplementedError


async def bm25_retrieve(query: str, bank: str, top_k: int = 20) -> List[RetrievalResult]:
    """BM25 keyword retrieval with jieba tokenization."""
    # TODO: Port from kb-web server.py build_bm25_index() + bm25 search
    raise NotImplementedError


def rrf_merge(
    dense_results: List[RetrievalResult],
    bm25_results: List[RetrievalResult],
    k: int = 60,
) -> List[RetrievalResult]:
    """Reciprocal Rank Fusion merge of dense + BM25 results."""
    # TODO: Port from kb-web server.py rrf_merge()
    raise NotImplementedError


async def rerank(query: str, candidates: List[RetrievalResult], top_k: int = 10) -> List[RetrievalResult]:
    """LLM-based reranking of retrieval results."""
    # TODO: Port LLM Rerank logic
    raise NotImplementedError
