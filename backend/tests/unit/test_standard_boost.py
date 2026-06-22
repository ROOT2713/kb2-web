"""Unit tests for Phase C1: standard_boost service."""

import pytest
from app.services.standard_boost import (
    extract_standard_numbers,
    find_docs_by_standard_number,
    fetch_doc_chunks,
    boost_exact_standards,
)


class TestExtractStandardNumbers:
    def test_gb_t(self):
        assert "GB/T 22239" in extract_standard_numbers("GB/T 22239-2019 等保三级有哪些通用要求") \
            or "GB/T 22239-2019" in extract_standard_numbers("GB/T 22239-2019 等保三级有哪些通用要求") \
            or any("22239" in s for s in extract_standard_numbers("GB/T 22239-2019 等保三级有哪些通用要求"))

    def test_jjf(self):
        nums = extract_standard_numbers("JJF 1059.1-2012 测量不确定度")
        assert any("1059" in n for n in nums), nums

    def test_jjg(self):
        nums = extract_standard_numbers("JJG 1071-2019 校准")
        assert any("1071" in n for n in nums), nums

    def test_gy(self):
        nums = extract_standard_numbers("GY 5055-2008 扩声会议系统")
        assert any("5055" in n for n in nums), nums

    def test_multiple(self):
        nums = extract_standard_numbers("GB/T 22239 和 GB/T 28448 的关系")
        assert len(nums) == 2

    def test_none(self):
        assert extract_standard_numbers("RAG 系统准确率怎么提升") == []

    def test_tegag(self):
        nums = extract_standard_numbers("T/EGAG 010-2022 监理服务规范")
        assert len(nums) >= 1, nums

    def test_doc_number(self):
        # 粤府办〔2023〕22号
        nums = extract_standard_numbers("粤府办〔2023〕22号 是什么")
        assert len(nums) >= 1


class TestFindDocsByStandardNumber:
    def test_find_22239(self, db_session):
        # Should find GB/T 22239-2019 doc
        from app.models.document import Document
        doc = Document(
            doc_id="test-22239",
            title="GB/T 22239-2019 信息安全技术 网络安全等级保护基本要求",
            doc_type="gb_standard",
            bank="default",
            status="active",
            searchable=1,
        )
        db_session.add(doc)
        db_session.flush()

        matches = find_docs_by_standard_number(db_session, "GB/T 22239")
        assert len(matches) >= 1
        assert any(m["doc_id"] == "test-22239" for m in matches)

    def test_normalize_match(self, db_session):
        # Various title formats should still match
        from app.models.document import Document
        for did, title in [
            ("test-1", "GB_50057-2010_建筑物防雷设计规范"),
            ("test-2", "GB∕T 28449-2018"),  # uses 全角 ∕
            ("test-3", "GB_T+35273-2020+《信息安全技术 个人信息安全规范》"),
        ]:
            db_session.add(Document(
                doc_id=did, title=title, doc_type="gb_standard",
                bank="default", status="active", searchable=1,
            ))
        db_session.flush()

        assert any(m["doc_id"] == "test-1" for m in find_docs_by_standard_number(db_session, "GB 50057"))
        assert any(m["doc_id"] == "test-2" for m in find_docs_by_standard_number(db_session, "GB/T 28449"))
        assert any(m["doc_id"] == "test-3" for m in find_docs_by_standard_number(db_session, "GB/T 35273"))

    def test_no_match(self, db_session):
        matches = find_docs_by_standard_number(db_session, "GB/T 99999")
        assert matches == []

    def test_too_short(self, db_session):
        # Avoid matching too-short tokens (would match too many docs)
        assert find_docs_by_standard_number(db_session, "GB") == []
        assert find_docs_by_standard_number(db_session, "AB") == []


class TestFetchDocChunks:
    def test_fetch(self, db_session):
        from app.models.document import Document, ParentChunk
        db_session.add(Document(doc_id="test-chunks", title="Test Doc", bank="default",
                                status="active", searchable=1))
        for i in range(10):
            db_session.add(ParentChunk(doc_id="test-chunks", parent_idx=i, parent_text=f"chunk {i} content"))
        db_session.flush()

        chunks = fetch_doc_chunks(db_session, "test-chunks", max_chunks=5)
        # >5 total → skip first 2, take next 5
        assert len(chunks) == 5
        assert chunks[0][1] == 2  # First returned chunk is parent_idx=2

    def test_few_chunks(self, db_session):
        from app.models.document import Document, ParentChunk
        db_session.add(Document(doc_id="test-few", title="Test", bank="default",
                                status="active", searchable=1))
        for i in range(3):
            db_session.add(ParentChunk(doc_id="test-few", parent_idx=i, parent_text=f"c{i}"))
        db_session.flush()

        chunks = fetch_doc_chunks(db_session, "test-few", max_chunks=5)
        assert len(chunks) == 3  # Don't skip when there's only a few


class TestBoostExactStandards:
    def test_inject_when_missing(self, db_session):
        from app.models.document import Document, ParentChunk
        # Set up doc not in initial doc_facts
        db_session.add(Document(doc_id="22239-test", title="GB/T 22239-2019 等保基本要求",
                                doc_type="gb_standard", bank="default", status="active", searchable=1))
        for i in range(5):
            db_session.add(ParentChunk(doc_id="22239-test", parent_idx=i,
                                       parent_text=f"22239 chunk {i} 第三级安全要求"))
        db_session.flush()

        # doc_facts starts empty (simulating Hindsight missing it)
        doc_facts = {}
        title_map = {}
        stats = boost_exact_standards(
            db_session, "GB/T 22239-2019 等保三级有哪些通用要求",
            doc_facts, title_map,
        )
        assert stats["std_nums_detected"] >= 1
        assert stats["docs_injected"] == 1
        assert stats["chunks_injected"] >= 3
        assert "22239-test" in doc_facts
        assert title_map["22239-test"] == "GB/T 22239-2019 等保基本要求"

    def test_boost_to_front_when_present(self, db_session):
        from app.models.document import Document, ParentChunk
        db_session.add(Document(doc_id="22239-test2", title="GB/T 22239-2019",
                                doc_type="gb_standard", bank="default", status="active", searchable=1))
        db_session.add(ParentChunk(doc_id="22239-test2", parent_idx=0, parent_text="content"))
        db_session.flush()

        # Doc 22239 already in doc_facts but at end (rank 2)
        doc_facts = {
            "other-doc-1": [("other1", "other1", "other1", 0)],
            "other-doc-2": [("other2", "other2", "other2", 0)],
            "22239-test2": [("existing", "existing", "existing", 0)],
        }
        title_map = {"22239-test2": "GB/T 22239-2019"}
        stats = boost_exact_standards(db_session, "GB/T 22239", doc_facts, title_map)
        # Doc not re-injected (no new chunks added)
        assert stats["docs_injected"] == 0
        # But boosted to front
        assert stats.get("docs_boosted", 0) == 1
        assert list(doc_facts.keys())[0] == "22239-test2"
        # Original entries preserved
        assert len(doc_facts["22239-test2"]) == 1

    def test_no_std_in_query(self, db_session):
        doc_facts = {}
        title_map = {}
        stats = boost_exact_standards(db_session, "什么是 RAG", doc_facts, title_map)
        assert stats["std_nums_detected"] == 0
        assert stats["docs_injected"] == 0
        assert doc_facts == {}
