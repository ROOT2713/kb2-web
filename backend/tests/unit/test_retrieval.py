"""Unit tests for retrieval reranking helpers."""

from app.services.retrieval import keyword_rerank


def _candidate(doc_id: str, text: str, title: str = "") -> dict:
    tags = [f"doc_id:{doc_id}"]
    if title:
        tags.append(f"title:{title}")
    return {"doc_id": doc_id, "text": text, "tags": tags}


def test_keyword_rerank_preserves_rrf_top_candidates():
    candidates = [
        _candidate("semantic-hit", "本段描述个人敏感信息的处理要求，但未重复查询中的隐私数据字样。"),
        _candidate("literal-hit", "隐私数据 隐私数据 隐私数据 管理要求。"),
        _candidate("other", "普通上下文。"),
    ]

    ranked = keyword_rerank("隐私数据", candidates, top_k=2)

    assert ranked[0]["doc_id"] == "semantic-hit"
    assert {item["doc_id"] for item in ranked} == {"semantic-hit", "literal-hit"}


def test_keyword_rerank_keeps_document_diversity_before_keyword_fill():
    candidates = [
        _candidate("doc-a", "低关键词但原始排序第一。"),
        _candidate("doc-a", "低关键词但同文档第二。"),
        _candidate("doc-b", "另一篇文档，语义相关。"),
        _candidate("doc-c", "关键词 命中 很多 关键词。"),
    ]

    ranked = keyword_rerank("关键词", candidates, top_k=3)

    assert "doc-b" in [item["doc_id"] for item in ranked]
    assert len(ranked) == 3
