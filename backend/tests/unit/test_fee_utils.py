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
    _FEE_WHITELIST,
    _FEE_KEYWORDS,
    filter_conflicting_fee_types,
)


# ═══════════════════════════════════════════════════════════════════
# Sanity: constants
# ═══════════════════════════════════════════════════════════════════

def test_fee_whitelist_not_empty():
    assert len(_FEE_WHITELIST) > 0, "_FEE_WHITELIST should have at least one keyword"


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
# Sanity: _FEE_WHITELIST coverage (used by retrieval.py)
# ═══════════════════════════════════════════════════════════════════

def test_whitelist_includes_core_fee_keywords():
    core = ["造价", "取费", "费用", "费率", "收费", "验收测评", "等保"]
    for kw in core:
        assert kw in _FEE_WHITELIST, f"'{kw}' should be in _FEE_WHITELIST"
