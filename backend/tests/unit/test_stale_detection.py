"""Tests for app.services.stale_detection — 过期检测服务。"""

import pytest
from datetime import datetime, timezone, timedelta
from app.services.stale_detection import (
    detect_stale_documents,
    restore_stale_document,
    get_stale_summary,
    _check_staleness,
)
from app.models.document import Document


class TestDetectStaleDocuments:
    """detect_stale_documents 集成测试。"""

    def test_never_verified_old_doc(self, db_session):
        """从未验证且创建超过阈值 → stale。"""
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        doc = Document(
            doc_id="old-001",
            title="旧文档",
            bank="general",
            status="active",
            created_at=old_date,
            updated_at=old_date,
        )
        db_session.add(doc)
        db_session.commit()

        result = detect_stale_documents(db_session, max_days=90, dry_run=True)
        assert result["stale_count"] == 1
        assert result["stale_docs"][0]["doc_id"] == "old-001"
        assert "never_verified" in result["stale_docs"][0]["stale_reason"]

    def test_recent_doc_not_stale(self, db_session):
        """新文档不标记为 stale。"""
        doc = Document(
            doc_id="new-001",
            title="新文档",
            bank="general",
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(doc)
        db_session.commit()

        result = detect_stale_documents(db_session, max_days=90, dry_run=True)
        assert result["stale_count"] == 0

    def test_verified_recently(self, db_session):
        """最近验证过的文档不 stale。"""
        doc = Document(
            doc_id="verified-001",
            title="已验证",
            bank="general",
            status="active",
            verified_at=datetime.now(timezone.utc) - timedelta(days=10),
            created_at=datetime.now(timezone.utc) - timedelta(days=100),
        )
        db_session.add(doc)
        db_session.commit()

        result = detect_stale_documents(db_session, max_days=90, dry_run=True)
        assert result["stale_count"] == 0

    def test_superseded_not_checked(self, db_session):
        """superseded 文档不检测。"""
        doc = Document(
            doc_id="super-001",
            title="旧版本",
            bank="general",
            status="superseded",
            created_at=datetime.now(timezone.utc) - timedelta(days=200),
        )
        db_session.add(doc)
        db_session.commit()

        result = detect_stale_documents(db_session, max_days=90, dry_run=True)
        assert result["stale_count"] == 0

    def test_dry_run_no_modification(self, db_session):
        """dry_run 模式不修改数据库。"""
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        doc = Document(
            doc_id="dry-001",
            title="dry run 测试",
            bank="general",
            status="active",
            created_at=old_date,
        )
        db_session.add(doc)
        db_session.commit()

        detect_stale_documents(db_session, max_days=90, dry_run=True)

        doc = db_session.query(Document).filter(Document.doc_id == "dry-001").first()
        assert doc.status == "active"  # 未修改

    def test_mark_stale(self, db_session):
        """非 dry_run 模式标记 stale。"""
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        doc = Document(
            doc_id="mark-001",
            title="将被标记",
            bank="general",
            status="active",
            created_at=old_date,
        )
        db_session.add(doc)
        db_session.commit()

        result = detect_stale_documents(db_session, max_days=90, dry_run=False)
        assert result["stale_count"] == 1

        doc = db_session.query(Document).filter(Document.doc_id == "mark-001").first()
        assert doc.status == "stale"
        assert doc.stale_at is not None
        assert doc.stale_reason is not None


class TestRestoreStaleDocument:
    """restore_stale_document 集成测试。"""

    def test_restore_stale(self, db_session):
        """恢复 stale 文档为 active。"""
        doc = Document(
            doc_id="restore-001",
            title="待恢复",
            bank="general",
            status="stale",
            stale_at=datetime.now(timezone.utc),
            stale_reason="never_verified",
        )
        db_session.add(doc)
        db_session.commit()

        result = restore_stale_document(db_session, "restore-001")
        assert result is True

        doc = db_session.query(Document).filter(Document.doc_id == "restore-001").first()
        assert doc.status == "active"
        assert doc.stale_at is None
        assert doc.stale_reason is None
        assert doc.verified_at is not None

    def test_restore_non_stale_fails(self, db_session):
        """非 stale 文档无法恢复。"""
        doc = Document(
            doc_id="active-001",
            title="活跃文档",
            bank="general",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        result = restore_stale_document(db_session, "active-001")
        assert result is False

    def test_restore_nonexistent_fails(self, db_session):
        """不存在的文档返回 False。"""
        result = restore_stale_document(db_session, "nonexistent")
        assert result is False


class TestGetStaleSummary:
    """get_stale_summary 集成测试。"""

    def test_summary(self, db_session):
        """统计各状态文档数量。"""
        # Clean slate (defend against leakage from prior tests in the same module)
        from sqlalchemy import text as _sa_text
        db_session.execute(_sa_text("DELETE FROM documents"))
        db_session.commit()

        docs = [
            Document(doc_id=f"doc-{i}", title=f"Doc {i}", bank="general", status="active")
            for i in range(5)
        ]
        docs.append(Document(doc_id="stale-001", title="Stale", bank="general", status="stale", stale_reason="never_verified"))
        docs.append(Document(doc_id="super-001", title="Super", bank="general", status="superseded"))
        db_session.add_all(docs)
        db_session.commit()

        result = get_stale_summary(db_session)
        assert result["active"] == 5
        assert result["stale"] == 1
        assert result["superseded"] == 1
        assert result["total"] == 7
        assert result["stale_by_reason"]["never_verified"] == 1
