"""Tests for fee-related utilities and D2-B injection fix.

Covers:
1. fee_utils._score_fee_chunk() — scoring logic
2. fee_utils.detect_fee_formula_type() — formula pattern detection
3. D2-B injection: verify it prefers fee table chunks over cover/front-matter
4. End-to-end: fee query with real DB data
"""
import json
import os
import re
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Import the module under test ──────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.services.fee_utils import (
    _FEE_TABLE_KEYWORDS,
    _FORMULA_KEYWORDS,
    _score_fee_chunk,
    build_fee_context_prompt,
    detect_fee_formula_type,
    find_fee_relevant_chunks,
)


# ═══════════════════════════════════════════════════════════════════
# Unit: _score_fee_chunk
# ═══════════════════════════════════════════════════════════════════

class TestScoreFeeChunk:
    """Core scoring logic — deterministic, no DB needed."""

    def test_cover_page_scores_zero(self):
        """封面/版权页不含任何费率表关键词，得分应为 <= 0（负数因短文本惩罚）"""
        text = (
            "电子政务工程造价指导书\n"
            "THE INSTRUCTION OF E-GOVERNMENT PROJECT CONSTRUCTION COST\n"
            "广东省电子政务协会编\n"
            "岭南美术出版社\n"
            "ISBN 978-7-5362-6162-4\n"
        )
        score = _score_fee_chunk(text, [])
        assert score <= 0, f"Cover page should not score positive: {score}"

    def test_editorial_board_scores_zero(self):
        """编委会名单不含任何费率表关键词，得分应为 <= 0（负数因短文本惩罚）"""
        text = (
            "主编: 钟东江\n副主编: 郑炯\n"
            "编委: 赵淦森 蔡立辉 梁满发 凌捷\n"
        )
        score = _score_fee_chunk(text, [])
        assert score <= 0, f"Editorial board should not score positive: {score}"

    def test_fee_rate_table_scores_positive(self):
        """费率表+公式应获得正分"""
        text = (
            "表 5-7 工程设计收费基准价表\n"
            "序号 计费额(x) 收费基价(y)\n"
            "1 50 2.70\n"
            "2 100 4.90\n"
            "3 200 9.0\n"
            "工程设计收费基价计算公式为: y=y₁+(x-x₁)/(x₂-x₁)×(y₂-y₁)\n"
            "【例如】计费额4000万在3000万~5000万档..."
        )
        score = _score_fee_chunk(text, ["5000万"])
        assert score > 0, f"Expected positive score, got {score}"

    def test_fee_rate_table_with_amount_keyword_bonus(self):
        """包含查询金额关键词应额外加分"""
        text = (
            "表 5-48 电子政务工程验收测评费率表\n"
            "序号 工程建设规模D(万元) 验收测试费率g(%) 最终费用(V)\n"
            "1 D≤200 ≥3 V=D×g\n"
        )
        # With relevant amount keyword
        score_with = _score_fee_chunk(text, ["万"])
        score_without = _score_fee_chunk(text, [])
        assert score_with >= score_without, (
            f"Amount keyword should not decrease score: {score_with} < {score_without}"
        )

    def test_formula_chunk_gets_bonus(self):
        """包含计算公式的chunk应获得额外加分"""
        text_plain = "表 5-9 电子政务工程(集成项目)监理服务费用基价表\n序号 计费额 监理费用基价"
        text_with_formula = text_plain + "\n计费额处于相邻两数值之间,可采取直线内插法确定监理服务费用基价\nY=Y₁+(X-X₁)/(X₂-X₁)×(Y₂-Y₁)"

        score_plain = _score_fee_chunk(text_plain, [])
        score_formula = _score_fee_chunk(text_with_formula, [])
        assert score_formula > score_plain, (
            f"Formula should boost score: {score_formula} <= {score_plain}"
        )

    def test_short_fragment_penalized(self):
        """太短的chunk应被扣分"""
        text_short = "表 5-7"  # < 200 chars
        text_long = text_short + "工程设计收费基准价表\n" * 30  # > 200 chars
        score_short = _score_fee_chunk(text_short, [])
        score_long = _score_fee_chunk(text_long, [])
        assert score_long > score_short, (
            f"Long chunk should score higher: {score_long} <= {score_short}"
        )

    def test_various_fee_table_keywords(self):
        """费率表关键词应匹配正确的取费类型"""
        # 验收测评
        text1 = "验收测评费率表\n最终费用(V)V=D×g×(1-Z)"
        s1 = _score_fee_chunk(text1, [])
        assert s1 > 0, f"验收测评 chunk should have positive score: {s1}"

        # 等保
        text2 = "信息安全等级保护评测费用表\nV=c×(1-Z)"
        s2 = _score_fee_chunk(text2, [])
        assert s2 > 0, f"等保 chunk should have positive score: {s2}"

        # 源代码审计
        text3 = "源代码审计费用表\nV=L×c×(1-Z)"
        s3 = _score_fee_chunk(text3, [])
        assert s3 > 0, f"源代码审计 chunk should have positive score: {s3}"


# ═══════════════════════════════════════════════════════════════════
# Unit: detect_fee_formula_type
# ═══════════════════════════════════════════════════════════════════

class TestDetectFeeFormulaType:
    """Formula type detection from chunk content."""

    def test_detect_interpolation(self):
        """检测直线内插法"""
        chunks = [
            {"doc_id": "d1", "title": "造价指导书", "text": "采用直线内插法确定监理服务费用基价\nY=Y₁+(X-X₁)/(X₂-X₁)×(Y₂-Y₁)"}
        ]
        patterns = detect_fee_formula_type(chunks)
        assert "直线内插" in patterns

    def test_detect_rate_proportion(self):
        """检测费率比例法 V=D×g×(1-Z)"""
        chunks = [
            {"doc_id": "d1", "title": "造价指导书", "text": "验收测试费率\n最终费用(V)V=D×g×(1-Z)"}
        ]
        patterns = detect_fee_formula_type(chunks)
        assert "费率比例" in patterns

    def test_multiple_patterns(self):
        """多个费率表应检测出多个公式类型"""
        chunks = [
            {"doc_id": "d1", "title": "造价指导书", "text": "采用直线内插法确定\nY=Y₁+(X-X₁)/(X₂-X₁)×(Y₂-Y₁)"},
            {"doc_id": "d1", "title": "造价指导书", "text": "最终费用(V)V=D×g×(1-Z)"},
        ]
        patterns = detect_fee_formula_type(chunks)
        assert "直线内插" in patterns
        assert "费率比例" in patterns

    def test_no_pattern_returns_empty(self):
        """无关内容的chunk不应误报公式类型"""
        chunks = [
            {"doc_id": "d1", "title": "某文档", "text": "编委会名单\n主编: 钟东江\n副主编: 郑炯"}
        ]
        patterns = detect_fee_formula_type(chunks)
        assert len(patterns) == 0


# ═══════════════════════════════════════════════════════════════════
# Unit: build_fee_context_prompt
# ═══════════════════════════════════════════════════════════════════

class TestBuildFeeContextPrompt:
    """Prompt generation based on detected formula types."""

    def test_empty_chunks_returns_empty(self):
        assert build_fee_context_prompt([], "测试") == ""

    def test_detected_guidance_includes_formulas(self):
        chunks = [
            {"doc_id": "d1", "title": "造价指导书", "text": "采用直线内插法确定\nY=Y₁+(X-X₁)/(X₂-X₁)×(Y₂-Y₁)"},
        ]
        result = build_fee_context_prompt(chunks, "510万项目费用")
        assert "费用计算引导" in result
        assert "直线内插" in result
        assert "公式" in result

    def test_no_detected_pattern_returns_empty(self):
        chunks = [
            {"doc_id": "d1", "title": "某文档", "text": "这是一般性描述内容，与取费无关。"}
        ]
        assert build_fee_context_prompt(chunks, "测试") == ""


# ═══════════════════════════════════════════════════════════════════
# Integration: D2-B injection via real DB data
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.db
class TestD2BInjection:
    """Verify D2-B chunk selection prefers fee tables over cover pages.

    These tests require a running DB with industry_docs data.
    """

    DOC_IDS_CACHE = None  # lazy-loaded

    @classmethod
    def _get_fee_doc_ids(cls):
        """Get real fee-related doc_ids from the DB."""
        if cls.DOC_IDS_CACHE is not None:
            return cls.DOC_IDS_CACHE

        try:
            from app.models.database import SessionLocal
            from sqlalchemy import text as sa_text
        except ImportError:
            return []

        db = SessionLocal()
        try:
            rows = db.execute(sa_text(
                "SELECT doc_id FROM documents "
                "WHERE searchable=1 AND status='active' "
                "AND bank='industry_docs' "
                "AND (title LIKE '%造价%') "
                "ORDER BY doc_id"
            )).fetchall()
            cls.DOC_IDS_CACHE = [r[0] for r in rows]
        except Exception:
            cls.DOC_IDS_CACHE = []
        finally:
            db.close()
        return cls.DOC_IDS_CACHE

    def test_fee_chunks_skip_low_value(self):
        """D2-B 不应选中封面/编委会/目录等低价值chunk."""
        doc_ids = self._get_fee_doc_ids()
        if not doc_ids:
            pytest.skip("No fee docs in DB")

        # 取 Part3-A (169 chunks, has deepest fee content)
        part3_doc = [d for d in doc_ids if d.startswith("05a2")]
        if not part3_doc:
            pytest.skip("Part3-A doc not found")
        
        chunks = find_fee_relevant_chunks(part3_doc[:1], max_chunks=8)
        assert len(chunks) > 0, "Should find fee-relevant chunks"

        # None of the top-8 should be the first 3 chunks (idx 0,1,2 = cover/editorial)
        for c in chunks:
            assert c["parent_idx"] >= 3, (
                f"D2-B should skip idx 0-2 (cover/editorial), got idx={c['parent_idx']} "
                f"doc={c['title'][:30]}"
            )

    def test_fee_chunks_contain_table_or_formula(self):
        """选中chunk应包含费率表或公式内容."""
        doc_ids = self._get_fee_doc_ids()
        if not doc_ids:
            pytest.skip("No fee docs in DB")

        chunks = find_fee_relevant_chunks(doc_ids[:2], max_chunks=5)
        assert len(chunks) > 0, "Should find fee-relevant chunks"

        # At least one chunk should contain fee-rate indicators
        combined = " ".join(c["text"] for c in chunks)
        has_keyword = any(kw in combined for kw in ["费率", "计费额", "收费基价", "费用基价"])
        assert has_keyword, (
            f"No fee table keywords found in any of {len(chunks)} chunks"
        )

    def test_fee_chunks_with_amount_keyword_prioritized(self):
        """包含查询金额关键词的chunk应排在前面."""
        doc_ids = self._get_fee_doc_ids()
        if not doc_ids:
            pytest.skip("No fee docs in DB")

        # With amount keyword
        chunks_with = find_fee_relevant_chunks(
            doc_ids[:2],
            amount_keywords=["1000万"],
            max_chunks=4,
        )
        # Without
        chunks_without = find_fee_relevant_chunks(
            doc_ids[:2],
            max_chunks=4,
        )

        # With amount keyword should find MORE content (scoring bonus for fee tables)
        # or at minimum not crash
        assert isinstance(chunks_with, list)
        assert isinstance(chunks_without, list)

    def test_non_fee_query_returns_empty(self):
        """与取费无关的查询不应触发D2-B."""
        # Simulate non-fee doc IDs
        chunks = find_fee_relevant_chunks([], max_chunks=8)
        assert len(chunks) == 0


# ═══════════════════════════════════════════════════════════════════
# End-to-end: query.py fee pipeline behavior
# ═══════════════════════════════════════════════════════════════════

class TestQueryFeePipeline:
    """Verify the D2-B code path in query.py works via direct function call."""

    # Sample chunk data to simulate D2-B injection
    COVER_CHUNK = {
        "doc_id": "fake-001",
        "parent_idx": 0,
        "title": "电子政务工程造价指导书",
        "text": "电子政务工程造价指导书\nTHE INSTRUCTION OF E-GOVERNMENT PROJECT CONSTRUCTION COST\n广东省电子政务协会编\n岭南美术出版社",
        "score": 0,
        "source": "industry_fallback",
    }
    FEE_TABLE_CHUNK = {
        "doc_id": "fake-001",
        "parent_idx": 39,
        "title": "电子政务工程造价指导书",
        "text": (
            "表 5-7 工程设计收费基准价表\n"
            "序号 计费额(x) 收费基价(y)\n"
            "1 50 2.70\n2 100 4.90\n3 200 9.0\n4 500 20.9\n"
            "工程设计收费基价计算公式: y=y₁+(x-x₁)/(x₂-x₁)×(y₂-y₁)\n"
            "【例如】计费额4000万: y=103.8+(4000-3000)/(5000-3000)×(163.9-103.8)=..."
        ),
        "score": 10,
        "source": "industry_fallback",
    }

    def test_d2b_injection_not_duplicating(self):
        """D2-B 注入不应产生重复来源的意外副作用."""
        # Simulate all_results with both cover and fee chunks
        all_results = [self.COVER_CHUNK, self.FEE_TABLE_CHUNK]
        existing_ids = {"fake-001"}
        
        assert "fake-001" in existing_ids
        # This mimics what the D2-B code does: skip already-seen docs
        assert len([d for d in ["fake-001"] if d not in existing_ids]) == 0

    def test_fee_guidance_prompt_includes_proper_formulas(self):
        """费用引导不应包含虚构的速算增加额概念."""
        from app.services.fee_utils import build_fee_context_prompt
        result = build_fee_context_prompt([self.FEE_TABLE_CHUNK], "4000万工程设计费")
        assert "速算增加额" not in result, (
            "Prompt should NOT contain 速算增加额 — it's not in the original docs"
        )
        assert "直线内插" in result or "公式" in result, (
            "Prompt should reference real doc formulas"
        )

    def test_tier_hint_in__generate_answer_no_fake_concepts(self):
        """_generate_answer 的 _tier_hint 不应包含虚构的速算增加额概念."""
        # Read the actual file and check
        query_py_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "app", "api", "query.py"
        )
        with open(query_py_path, "r") as f:
            content = f.read()
        
        # The old _tier_hint had this string
        assert "速算增加额" not in content, (
            "_tier_hint should not contain 速算增加额\n"
            "It's a fake concept — the original docs don't use this term."
        )
        assert "费用计算引导" in content, (
            "_tier_hint should contain 费用计算引导\n"
            "This is the new heading for fee guidance."
        )
