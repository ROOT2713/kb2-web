"""Tests for fee-related utilities (post-D2-B-simplification, 2026-07-30).

Replaces old D2-B tests (find_fee_relevant_chunks, _score_fee_chunk, etc.)
With new filter_conflicting_fee_types() tests.
"""

import json
import os
import sys

# ── Import the module under test ──────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.services.fee_utils import (
    _FEE_KEYWORDS,
    fee_intent,
    filter_conflicting_fee_types,
)


# ═══════════════════════════════════════════════════════════════════
# Sanity: constants
# ═══════════════════════════════════════════════════════════════════

def test_fee_keywords_not_empty():
    assert len(_FEE_KEYWORDS) > 0, "_FEE_KEYWORDS should have at least one keyword"


# ═══════════════════════════════════════════════════════════════════
# Unit: filter_conflicting_fee_types
# ═══════════════════════════════════════════════════════════════════

class TestFilterConflictingFeeTypes:

    def test_empty_results(self):
        """Empty list should return empty list."""
        result = filter_conflicting_fee_types([], "等保测评费")
        assert result == []

    def test_no_fee_type_in_query(self):
        """Query without fee keywords should not reorder."""
        chunks = [
            {"text": "验收测评服务费 2.0%", "doc_id": "doc1"},
            {"text": "等保测评服务费 3.0%", "doc_id": "doc2"},
        ]
        result = filter_conflicting_fee_types(chunks, "数据中心机房温度要求")
        assert len(result) == 2
        # Order unchanged
        assert result[0]["doc_id"] == "doc1"

    def test_demote_conflicting_type(self):
        """等保 query should demote 验收测评 chunks."""
        chunks = [
            {"text": "验收测评服务费 2.0%，速算增加额0", "doc_id": "doc1"},
            {"text": "等保测评服务费 3.0%，V=D×g", "doc_id": "doc2"},
            {"text": "监理服务费 1.5%", "doc_id": "doc3"},
        ]
        result = filter_conflicting_fee_types(chunks, "等保测评费")
        # 等保 chunk should be first, 验收测评 should be last
        assert result[0]["doc_id"] == "doc2", f"Expected doc2 first, got {result[0]['doc_id']}"
        assert result[-1]["doc_id"] == "doc1", f"Expected doc1 last, got {result[-1]['doc_id']}"

    def test_no_demote_when_chunk_also_mentions_queried_type(self):
        """Chunk mentioning both queried type and conflicting type should not be demoted."""
        chunks = [
            {"text": "等级保护测评服务（含差距测评、验收测评服务）3.0%", "doc_id": "doc1"},
            {"text": "验收测评服务费 2.0%", "doc_id": "doc2"},
        ]
        result = filter_conflicting_fee_types(chunks, "等保测评费")
        # doc1 mentions both 等保 and 验收测评 → not demoted
        # doc2 only mentions 验收测评 → demoted
        assert result[0]["doc_id"] == "doc1"
        assert result[-1]["doc_id"] == "doc2"

    def test_acceptance_testing_query_not_affected(self):
        """验收测评 query should NOT demote 等保 chunks (exclusion is one-way)."""
        chunks = [
            {"text": "等保测评服务费 3.0%", "doc_id": "doc1"},
            {"text": "验收测评服务费 2.0%", "doc_id": "doc2"},
        ]
        result = filter_conflicting_fee_types(chunks, "验收测评费")
        # Order unchanged — 验收测评 exclusions is empty set
        assert len(result) == 2
        # Both should still be there (no removal)
        doc_ids = [c["doc_id"] for c in result]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids


# ═══════════════════════════════════════════════════════════════════
# fee_intent —— 全库唯一权威费用意图闸门（2026-10-13 v5.1 归一）
#
# 取代原 _FEE_WHITELIST：全库 8 处散落词表统一为 fee_intent() 后，
# 该常量已删除 —— 本组用例即为它的接替覆盖（含 v5.1 的两条设计约束）。
# ═══════════════════════════════════════════════════════════════════

class TestFeeIntent:

    def test_topic_word_alone_is_not_fee_intent(self):
        """主题词（等保/密评/商密）本身不算费用意图 —— 必须再配"钱"线索。"""
        assert fee_intent("等保测评的流程是什么") is False
        assert fee_intent("密评备案材料有哪些") is False

    def test_topic_word_plus_money_cue(self):
        assert fee_intent("等保测评费用多少") is True
        assert fee_intent("密评收费标准") is True

    def test_fee_char_negative_lookbehind(self):
        """「费」的否定环视：消费 / 免费 / 浪费 均不算费用意图。"""
        assert fee_intent("这个软件免费吗") is False
        assert fee_intent("避免浪费资源") is False
        assert fee_intent("消费级设备选型") is False

    def test_fee_plus_action_generalizes(self):
        """泛化「X费 + 费用动作」——覆盖词表穷举不完的写法。"""
        assert fee_intent("监理服务费怎么算") is True
        assert fee_intent("招标代理费怎么收") is True

    def test_money_only_word_requires_fee_word(self):
        """v5.1：金钱词（金额/比例/万元）须与费用词共现，单独出现不算。"""
        assert fee_intent("资金调整数额不超过总金额多少比例") is False

    def test_geo_word_alone_is_not_fee_intent(self):
        """提及地市 ≠ 问费用（geo 词不单独触发）。"""
        assert fee_intent("佛山政务云建设要求") is False

    def test_unrelated_query(self):
        assert fee_intent("机房温度要求是多少") is False
        assert fee_intent("") is False
