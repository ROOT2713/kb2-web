"""Tests for app.services.quality_gates — 三级质量门禁。"""

import pytest
from app.services.quality_gates import (
    check_document,
    check_all_documents,
    _check_g1_format,
    _check_g2_completeness,
    _check_g3_consistency,
)
from app.models.document import Document
from app.models.concept import Concept


class TestG1Format:
    """G1 格式检查。"""

    def test_good_document(self, db_session):
        """格式完好的文档通过 G1。"""
        doc = Document(
            doc_id="g1-good-001",
            title="测试文档",
            bank="general",
            doc_type="gb_standard",
            original_text_length=5000,
            chunk_count=10,
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g1-good-001", "G1")
        assert result["overall_passed"] is True
        assert result["gates"][0]["gate"] == "G1"

    def test_short_content(self, db_session):
        """内容过短扣分。"""
        doc = Document(
            doc_id="g1-short-001",
            title="短文档",
            bank="general",
            original_text_length=50,
            chunk_count=1,
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g1-short-001", "G1")
        assert result["gates"][0]["passed"] is False
        assert any("过短" in i for i in result["gates"][0]["issues"])

    def test_no_chunks(self, db_session):
        """无分块扣分。"""
        doc = Document(
            doc_id="g1-nochunk-001",
            title="无分块",
            bank="general",
            original_text_length=1000,
            chunk_count=0,
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g1-nochunk-001", "G1")
        assert any("分块" in i for i in result["gates"][0]["issues"])


class TestG2Completeness:
    """G2 完整性检查。"""

    def test_complete_document(self, db_session):
        """完整文档通过 G2。"""
        doc = Document(
            doc_id="g2-good-001",
            title="完整文档",
            bank="general",
            doc_type="gb_standard",
            concept_id="standards/test/doc",
            domain="standards",
            chunk_count=3,
        )
        # 创建足够的 concepts 使比率 > 0.3
        concepts = [
            Concept(
                concept_id=f"g2-good-001/section-{i}",
                doc_id="g2-good-001",
                parent_idx=i,
                title=f"Section {i}",
                content=f"Content for section {i} with enough text",
                status="active",
            )
            for i in range(2)
        ]
        db_session.add_all([doc] + concepts)
        db_session.commit()

        result = check_document(db_session, "g2-good-001", "G2")
        assert result["overall_passed"] is True

    def test_missing_concept_id(self, db_session):
        """缺少 concept_id 扣分。"""
        doc = Document(
            doc_id="g2-nocid-001",
            title="无 concept",
            bank="general",
            chunk_count=5,
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g2-nocid-001", "G2")
        assert any("concept_id" in i for i in result["gates"][0]["issues"])

    def test_no_concepts(self, db_session):
        """无 concept 记录扣分。"""
        doc = Document(
            doc_id="g2-noconcepts-001",
            title="无概念",
            bank="general",
            concept_id="test/doc",
            domain="test",
            chunk_count=5,
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g2-noconcepts-001", "G2")
        assert any("concept 记录" in i for i in result["gates"][0]["issues"])


class TestG3Consistency:
    """G3 一致性检查。"""

    def test_consistent_document(self, db_session):
        """一致性完好的文档通过 G3。"""
        doc = Document(
            doc_id="g3-good-001",
            title="GB/T 50116-2013 测试",
            bank="standard",
            doc_type="gb_standard",
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g3-good-001", "G3")
        assert result["overall_passed"] is True

    def test_gb_missing_standard_number(self, db_session):
        """GB 标准缺标准号扣分。"""
        doc = Document(
            doc_id="g3-nostd-001",
            title="某标准文档",
            bank="standard",
            doc_type="gb_standard",
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g3-nostd-001", "G3")
        assert any("标准号" in i for i in result["gates"][0]["issues"])

    def test_broken_superseded_by(self, db_session):
        """superseded_by 引用不存在扣分。"""
        doc = Document(
            doc_id="g3-broken-001",
            title="引用断裂",
            bank="general",
            superseded_by="nonexistent-doc",
        )
        db_session.add(doc)
        db_session.commit()

        result = check_document(db_session, "g3-broken-001", "G3")
        assert any("superseded_by" in i for i in result["gates"][0]["issues"])

    def test_duplicate_title(self, db_session):
        """同 bank 下重复标题扣分。"""
        doc1 = Document(doc_id="g3-dup-001", title="重复标题", bank="general", status="active")
        doc2 = Document(doc_id="g3-dup-002", title="重复标题", bank="general", status="active")
        db_session.add_all([doc1, doc2])
        db_session.commit()

        result = check_document(db_session, "g3-dup-001", "G3")
        assert any("重复标题" in i for i in result["gates"][0]["issues"])


class TestCheckAllDocuments:
    """check_all_documents 批量检查。"""

    def test_batch_check(self, db_session):
        """批量检查多个文档。"""
        docs = [
            Document(doc_id=f"batch-{i}", title=f"Doc {i}", bank="general",
                     original_text_length=1000, chunk_count=5)
            for i in range(3)
        ]
        db_session.add_all(docs)
        db_session.commit()

        result = check_all_documents(db_session, "G1", limit=10)
        assert result["total_checked"] == 3
        assert result["passed"] + result["failed"] == 3

    def test_not_found(self, db_session):
        """不存在的文档返回 error。"""
        result = check_document(db_session, "nonexistent", "G1")
        assert "error" in result
