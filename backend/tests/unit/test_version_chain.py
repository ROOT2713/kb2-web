"""Tests for app.services.version_chain — 版本链管理。"""

import pytest
from datetime import datetime, timezone
from app.services.version_chain import (
    detect_existing_doc,
    mark_superseded,
    get_version_history,
    _extract_standard_number,
)
from app.models.document import Document


class TestExtractStandardNumber:
    """_extract_standard_number 单元测试。"""

    def test_gb_t_standard(self):
        assert _extract_standard_number("GB/T 50116-2013 火灾自动报警") == "gb-t-50116-2013"

    def test_gb_standard(self):
        assert _extract_standard_number("GB 50016-2014 建筑设计防火") == "gb-50016-2014"

    def test_no_standard_number(self):
        assert _extract_standard_number("网络安全法") is None

    def test_empty_title(self):
        assert _extract_standard_number("") is None


class TestDetectExistingDoc:
    """detect_existing_doc 集成测试。"""

    def test_detect_by_content_hash(self, db_session):
        """content_hash 精确匹配。"""
        doc = Document(
            doc_id="doc-hash-001",
            title="测试文档",
            bank="general",
            doc_type="generic",
            content_hash="abc123hash",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        found = detect_existing_doc(
            db=db_session,
            title="其他标题",
            bank="general",
            content_hash="abc123hash",
        )
        assert found is not None
        assert found.doc_id == "doc-hash-001"

    def test_detect_by_standard_number(self, db_session):
        """同标准号匹配。"""
        doc = Document(
            doc_id="doc-std-001",
            title="GB/T 50116-2013 火灾自动报警系统设计规范",
            bank="standard",
            doc_type="gb_standard",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        found = detect_existing_doc(
            db=db_session,
            title="GB/T 50116-2013 火灾自动报警系统设计规范（修订版）",
            bank="standard",
            doc_type="gb_standard",
        )
        assert found is not None
        assert found.doc_id == "doc-std-001"

    def test_detect_by_title(self, db_session):
        """同标题匹配。"""
        doc = Document(
            doc_id="doc-title-001",
            title="网络安全法",
            bank="law",
            doc_type="regulation",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        found = detect_existing_doc(
            db=db_session,
            title="网络安全法",
            bank="law",
            doc_type="regulation",
        )
        assert found is not None
        assert found.doc_id == "doc-title-001"

    def test_no_match(self, db_session):
        """无匹配返回 None。"""
        found = detect_existing_doc(
            db=db_session,
            title="不存在的文档",
            bank="general",
        )
        assert found is None

    def test_different_bank_no_match(self, db_session):
        """不同 bank 不匹配。"""
        doc = Document(
            doc_id="doc-bank-001",
            title="同名文档",
            bank="general",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        found = detect_existing_doc(
            db=db_session,
            title="同名文档",
            bank="law",
        )
        assert found is None

    def test_superseded_doc_not_matched(self, db_session):
        """已 superseded 的文档不被匹配。"""
        doc = Document(
            doc_id="doc-super-001",
            title="旧版本",
            bank="general",
            status="superseded",
        )
        db_session.add(doc)
        db_session.commit()

        found = detect_existing_doc(
            db=db_session,
            title="旧版本",
            bank="general",
        )
        assert found is None


class TestMarkSuperseded:
    """mark_superseded 集成测试。"""

    def test_basic_supersede(self, db_session):
        """基本 supersede 操作。"""
        old = Document(doc_id="old-001", title="旧版", bank="general", status="active")
        new = Document(doc_id="new-001", title="新版", bank="general", status="active")
        db_session.add_all([old, new])
        db_session.commit()

        result = mark_superseded(db_session, "old-001", "new-001", "test_reason")
        assert result is True
        db_session.commit()

        old = db_session.query(Document).filter(Document.doc_id == "old-001").first()
        new = db_session.query(Document).filter(Document.doc_id == "new-001").first()

        assert old.status == "superseded"
        assert old.superseded_by == "new-001"
        assert old.stale_reason == "test_reason"
        assert new.supersedes == "old-001"

    def test_self_supersede_fails(self, db_session):
        """不能 supersede 自己。"""
        doc = Document(doc_id="self-001", title="自己", bank="general", status="active")
        db_session.add(doc)
        db_session.commit()

        result = mark_superseded(db_session, "self-001", "self-001")
        assert result is False

    def test_nonexistent_doc_fails(self, db_session):
        """不存在的文档返回 False。"""
        result = mark_superseded(db_session, "nonexistent", "also-nonexistent")
        assert result is False


class TestGetVersionHistory:
    """get_version_history 集成测试。"""

    def test_simple_chain(self, db_session):
        """两版本链：v1 → v2。"""
        v1 = Document(doc_id="v1-001", title="V1", version="1.0.0", bank="general", status="superseded", superseded_by="v2-001")
        v2 = Document(doc_id="v2-001", title="V2", version="2.0.0", bank="general", status="active", supersedes="v1-001")
        db_session.add_all([v1, v2])
        db_session.commit()

        result = get_version_history(db_session, "v1-001")
        assert "error" not in result
        assert result["current"]["doc_id"] == "v1-001"
        assert result["superseded_by"]["doc_id"] == "v2-001"
        assert result["supersedes"] is None
        assert len(result["chain"]) == 2

    def test_three_version_chain(self, db_session):
        """三版本链：v1 → v2 → v3。"""
        v1 = Document(doc_id="v1-001", title="V1", version="1.0.0", bank="general", status="superseded", superseded_by="v2-001")
        v2 = Document(doc_id="v2-001", title="V2", version="2.0.0", bank="general", status="superseded", superseded_by="v3-001", supersedes="v1-001")
        v3 = Document(doc_id="v3-001", title="V3", version="3.0.0", bank="general", status="active", supersedes="v2-001")
        db_session.add_all([v1, v2, v3])
        db_session.commit()

        result = get_version_history(db_session, "v2-001")
        assert len(result["chain"]) == 3
        assert result["chain"][0]["doc_id"] == "v3-001"  # 最新
        assert result["chain"][2]["doc_id"] == "v1-001"  # 最旧

    def test_not_found(self, db_session):
        """不存在的文档返回 error。"""
        result = get_version_history(db_session, "nonexistent")
        assert "error" in result
