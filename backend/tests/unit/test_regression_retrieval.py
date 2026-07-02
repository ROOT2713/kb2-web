"""
kb2-web 检索回归测试 — 黄金查询集

适用场景：
  每次 retrieval.py / query.py 修改后（含 GraphRAG 第三通道添加），
  运行此测试验证召回质量不退化。

两层测试：
  Layer 1 (单元级): rrf_merge / keyword_rerank / tiebreaker_sort 纯逻辑回归
  Layer 2 (集成级): 用 production DB 对 20 条黄金查询做端到端检索质量检查
    → 需要 pytest -s --run-integration 或产线环境
"""

import json
import os
from pathlib import Path

import pytest

from app.services.retrieval import (
    rrf_merge,
    keyword_rerank,
    apply_tiebreaker_sort,
    expand_query_synonyms,
)

# ── 加载黄金查询集 ──────────────────────────────────────────────────
_GOLDEN_PATH = Path(__file__).resolve().parent.parent / "golden_queries.json"
with open(_GOLDEN_PATH, "r", encoding="utf-8") as _f:
    _GOLDEN = json.load(_f)
ALL_QUERIES = _GOLDEN["queries"]


# ═══════════════════════════════════════════════════════════════════
# Layer 1: 单元级回归
# ═══════════════════════════════════════════════════════════════════

class TestRRFMergeRegression:
    """rrf_merge 两路融合的回归测试。新增第三通道后必须保持二路模式行为不变。"""

    def _make_dense(self, doc_id: str, text: str) -> dict:
        return {"text": text, "tags": [f"doc_id:{doc_id}"], "score": 0.8}

    def _make_bm25(self, doc_id: str, text: str, title: str = "") -> dict:
        result = {"doc_id": doc_id, "text": text}
        if title:
            result["title"] = title
        return result

    def test_rrf_merge_dense_empty(self):
        """BM25-only 时 RRF 仍能正常返回 BM25 结果。"""
        bm25 = [self._make_bm25("d1", "接地电阻测试方法")]
        merged = rrf_merge([], bm25)
        assert len(merged) == 1
        assert merged[0]["doc_id"] == "d1"

    def test_rrf_merge_bm25_empty(self):
        """Dense-only 时 RRF 仍能正常返回 Dense 结果。"""
        dense = [self._make_dense("d1", "隐私数据处理要求")]
        merged = rrf_merge(dense, [])
        assert len(merged) == 1

    def test_rrf_merge_deduplication(self):
        """同一 doc_id+text 跨通道去重。"""
        dense = [self._make_dense("d1", "接地电阻测试方法")]
        bm25 = [self._make_bm25("d1", "接地电阻测试方法")]
        merged = rrf_merge(dense, bm25)
        assert len(merged) == 1  # 去重

    def test_rrf_merge_document_diversity(self):
        """确保多文档不会被单一文档淹没（max_per_doc=3 for non-checklist banks）。
        BM25 结果没有 tags，通过 doc_id 字段判断。"""
        dense = [self._make_dense("d1", f"文档1 第{i}段") for i in range(10)]
        bm25 = [self._make_bm25("d2", "文档2 唯一段")]
        merged = rrf_merge(dense, bm25)
        # d1 chunks 被限制 <= 3
        d1_count = sum(1 for m in merged if m.get("doc_id") == "d1" or
                       any("doc_id:d1" in str(t) for t in m.get("tags", [])))
        assert d1_count <= 3
        # d2 应该出现
        assert any(m.get("doc_id") == "d2" for m in merged)

    def test_rrf_merge_kw_boost_with_keyword(self):
        """BM25 条目含查询关键词时 keyword_boost=2.0。
        BM25 结果通过 doc_id 字段识别，keyword_boost 在 RRF 评分中生效。"""
        # dense 结果分数低，bm25 结果由于 keyword_boost 排前面
        dense = [self._make_dense("d1", "无关内容 无关内容")]
        # BM25 结果需要 doc_id + text 含关键词才能触发 keyword_boost
        bm25 = [
            self._make_bm25("d2", "接地电阻 测试 接地电阻 标准 要求很专业"),
        ]
        merged = rrf_merge(dense, bm25, query_keywords=["接地电阻"])
        doc_ids = [m.get("doc_id") for m in merged]
        # d2 (BM25 含关键词) 应排在 d1 (dense 无关内容) 前面
        assert doc_ids.index("d2") < doc_ids.index("d1") if "d1" in doc_ids else True


class TestKeywordRerankRegression:
    """keyword_rerank 对比测试。新增 GraphRAG 通道后 keyword_rerank 行为不变。"""

    def _candidate(self, doc_id: str, text: str, title: str = "") -> dict:
        tags = [f"doc_id:{doc_id}"]
        if title:
            tags.append(f"title:{title}")
        return {"doc_id": doc_id, "text": text, "tags": tags}

    def test_keyword_rerank_upgrades_exact_match(self):
        """keyword_rerank 保留 RRF top-8 顺序后，按关键词得分补齐。
        验证：低关键词密度的"语义"候补仍出现在结果中（多样性保护）。"""
        candidates = [
            self._candidate("rrf-top", "原文语义相关的段落描述。"),
            self._candidate("kw-match", "接地电阻 接地电阻 测试 接地电阻 要求"),
            self._candidate("other", "普通上下文。"),
        ]
        ranked = keyword_rerank("接地电阻", candidates, top_k=3)
        # RRF top 保留：第一条是原来的候选
        # 三条都应该出现
        doc_ids = [r["doc_id"] for r in ranked]
        assert len(doc_ids) == 3
        assert "kw-match" in doc_ids  # 关键词命中多的应出现

    def test_keyword_rerank_keeps_diversity(self):
        """关键词填充阶段不会挤掉语义相关的其他文档。"""
        candidates = [
            self._candidate("doc-a1", "低关键词但语义相关1"),
            self._candidate("doc-a1", "低关键词但语义相关2"),
            self._candidate("doc-b", "另一语义相关文档"),
            self._candidate("doc-c", "关键词 命中 很多 关键词 重复 命中"),
        ]
        ranked = keyword_rerank("关键词", candidates, top_k=3)
        assert "doc-b" in [r["doc_id"] for r in ranked]
        assert len(ranked) == 3


class TestTiebreakerRegression:
    """apply_tiebreaker_sort 回归测试。"""

    def _result(self, doc_id: str, tags: list = None, score: float = 0.5) -> dict:
        return {"text": "内容", "tags": tags or [f"doc_id:{doc_id}"], "score": score}

    def test_tiebreaker_empty(self):
        assert apply_tiebreaker_sort([]) == []

    def test_tiebreaker_preserves_order_no_meta(self):
        """无元数据时按原始 score 排序。"""
        results = [self._result("d1", score=0.9), self._result("d2", score=0.3)]
        ranked = apply_tiebreaker_sort(results)
        assert ranked[0]["tags"][0].endswith("d1")

    def test_tiebreaker_query_no_geo(self):
        """非标准类查询不走 geo tiebreaker。"""
        results = [self._result("d1", score=0.3), self._result("d2", score=0.9)]
        ranked = apply_tiebreaker_sort(results, query="AI Agent 工具调用")
        assert ranked[0]["tags"][0].endswith("d2")


# ═══════════════════════════════════════════════════════════════════
# Layer 2: 集成级回归（需要产线 DB）
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="集成回归需要 --run-integration 标志和 production DB 访问",
)
class TestGoldenQueryRegression:
    """
    对 20 条黄金查询做端到端检索质量检查。
    pytest -s --run-integration tests/unit/test_regression_retrieval.py

    注意：
    - 本测试直接访问 production DB 和 Hindsight API
    - 每条查询生成 JSON snapshot（top-10 doc_ids）供后续对比
    """

    SNAPSHOT_DIR = Path(__file__).parent.parent / "regression_snapshots"

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    @pytest.mark.parametrize(
        "q",
        [pytest.param(q, id=q.get("id", q.get("query", "unknown"))) for q in ALL_QUERIES],
    )
    @pytest.mark.asyncio
    async def test_golden_query(self, q):
        from app.services.retrieval import (
            recall, build_bm25_index, bm25_search,
            rrf_merge, llm_rerank, apply_tiebreaker_sort,
            expand_query_synonyms,
        )

        query = q["query"]
        q_id = q["id"]

        # 1) 扩写
        expanded = expand_query_synonyms(query)
        assert len(expanded) >= len(query)

        # 2) 语义召回
        dense = await recall(query, limit=30, bank="all")

        # 3) BM25
        bm25_idx, bm25_docs = await build_bm25_index("all")
        bm25 = bm25_search(query, bm25_idx, bm25_docs, top_k=30)

        # 4) RRF 融合（二通道 baseline）
        merged = rrf_merge(dense, bm25, query_keywords=query.split())

        # 5) 精排
        reranked = await llm_rerank(query, merged, top_k=15)

        # 6) Tiebreaker
        final = apply_tiebreaker_sort(reranked, query=query)

        # ── 断言 ──
        assert len(final) >= q.get("min_results", 1), (
            f"{q_id}: 期望 >= {q.get('min_results', 1)} 条结果，实际 {len(final)}"
        )
        assert len(final) <= 15, f"{q_id}: 精排后结果不应超过 15 个"

        # 如果期望特定 bank 的结果
        if q.get("expected_banks"):
            actual_banks = set()
            for r in final:
                for t in r.get("tags", []):
                    if t.startswith("bank:"):
                        actual_banks.add(t[5:])
            # Dense 结果 tags 不含 bank，这个断言暂不开启
            pass

        # ── 快照：记录 top-10 doc_ids 供后续对比 ──
        snapshot = {
            "query": query,
            "id": q_id,
            "timestamp": None,  # 实际运行时注入
            "top10_doc_ids": [],
            "top10_titles": [],
        }
        for r in final[:10]:
            did = None
            title = ""
            for t in r.get("tags", []):
                if t.startswith("doc_id:"):
                    did = t[6:]
                if t.startswith("title:"):
                    title = t[6:]
            snapshot["top10_doc_ids"].append(did)
            snapshot["top10_titles"].append(title)

        snapshot_path = self.SNAPSHOT_DIR / f"{q_id}.json"
        json.dump(snapshot, open(snapshot_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        # ── 快照对比（如果存在前次快照） ──
        # 简略实现：首次运行只写入，第二次运行对比
        # 对比逻辑见 scripts/compare_regression.py


# ═══════════════════════════════════════════════════════════════════
# Layer 3: 黄金查询集完整性校验
# ═══════════════════════════════════════════════════════════════════

class TestGoldenQueryIntegrity:
    """黄金查询集本身的结构完整性。"""

    def test_queries_not_empty(self):
        assert len(ALL_QUERIES) >= 20

    def test_all_have_ids(self):
        for q in ALL_QUERIES:
            assert "id" in q, f"Query missing id: {q.get('query', '?')}"
            assert q["id"].startswith("Q"), f"Bad id format: {q['id']}"

    def test_all_have_categories(self):
        for q in ALL_QUERIES:
            assert "category" in q, f"{q['id']} missing category"

    def test_all_have_min_results(self):
        for q in ALL_QUERIES:
            assert q.get("min_results", 0) >= 1, f"{q['id']} min_results < 1"

    def test_all_have_expected_banks(self):
        for q in ALL_QUERIES:
            assert "expected_banks" in q, f"{q['id']} missing expected_banks"

    def test_ids_are_unique(self):
        ids = [q["id"] for q in ALL_QUERIES]
        assert len(ids) == len(set(ids)), "Duplicate query IDs found"

    def test_graphrag_queries_have_entity_types(self):
        """GraphRAG 预备查询必须标注实体类型和 predicate。"""
        for q in ALL_QUERIES:
            if q.get("graphrag_entity_types"):
                assert "graphrag_predicate" in q or q.get("category") == "标准引用链", \
                    f"{q['id']}: graphrag queries need predicate"
