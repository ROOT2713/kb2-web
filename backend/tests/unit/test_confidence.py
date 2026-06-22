"""Tests for app.services.confidence — 多维度知识置信度评分。"""

import pytest
from datetime import datetime, timezone, timedelta
from app.services.confidence import (
    compute_concept_confidence,
    compute_document_confidence,
    update_concept_confidence,
    update_all_confidences,
    get_confidence_summary,
    _time_decay_score,
)
from app.models.document import Document
from app.models.concept import Concept


class TestTimeDecayScore:
    """时间衰减评分单元测试。"""

    def test_recent_document(self):
        """新文档高分。"""
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        score = _time_decay_score(recent)
        assert score > 0.9

    def test_old_document(self):
        """旧文档低分。"""
        old = datetime.now(timezone.utc) - timedelta(days=365)
        score = _time_decay_score(old)
        assert score < 0.3

    def test_half_life(self):
        """半衰期验证。"""
        half_life = datetime.now(timezone.utc) - timedelta(days=180)
        score = _time_decay_score(half_life)
        assert 0.45 < score < 0.55  # 约 0.5

    def test_none_datetime(self):
        """None 返回中等分。"""
        assert _time_decay_score(None) == 0.5


class TestComputeConceptConfidence:
    """concept confidence 计算集成测试。"""

    def test_basic_confidence(self, db_session):
        """基本 confidence 计算。"""
        doc = Document(
            doc_id="conf-doc-001",
            title="测试文档",
            bank="general",
            domain="methodology",
            status="active",
        )
        concept = Concept(
            concept_id="conf-doc-001/section-0",
            doc_id="conf-doc-001",
            parent_idx=0,
            title="Section 0",
            content="Some content",
            confidence=0.5,
            status="active",
            access_count=10,
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add_all([doc, concept])
        db_session.commit()

        conf = compute_concept_confidence(db_session, "conf-doc-001/section-0")
        assert 0.0 <= conf <= 1.0
        assert conf > 0.3  # 应该有一定分数

    def test_nonexistent_concept(self, db_session):
        """不存在的 concept 返回 0。"""
        conf = compute_concept_confidence(db_session, "nonexistent")
        assert conf == 0.0


class TestComputeDocumentConfidence:
    """document confidence 计算集成测试。"""

    def test_document_with_concepts(self, db_session):
        """有 concept 的文档计算 confidence。"""
        doc = Document(
            doc_id="doc-conf-001",
            title="文档置信度",
            bank="general",
            domain="standards",
            status="active",
            updated_at=datetime.now(timezone.utc),
        )
        concepts = [
            Concept(
                concept_id=f"doc-conf-001/section-{i}",
                doc_id="doc-conf-001",
                parent_idx=i,
                title=f"Section {i}",
                content=f"Content {i}",
                confidence=0.6 + i * 0.1,
                status="active",
            )
            for i in range(3)
        ]
        db_session.add_all([doc] + concepts)
        db_session.commit()

        conf = compute_document_confidence(db_session, "doc-conf-001")
        assert 0.0 <= conf <= 1.0

    def test_empty_document(self, db_session):
        """无 concept 的文档返回 0。"""
        doc = Document(
            doc_id="doc-empty-001",
            title="空文档",
            bank="general",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        conf = compute_document_confidence(db_session, "doc-empty-001")
        assert conf == 0.0


class TestUpdateAllConfidences:
    """批量重算测试。"""

    def test_batch_update(self, db_session):
        """批量更新 confidence。"""
        doc = Document(doc_id="batch-001", title="批量", bank="general", domain="test", status="active")
        concepts = [
            Concept(
                concept_id=f"batch-001/section-{i}",
                doc_id="batch-001",
                parent_idx=i,
                title=f"Section {i}",
                content=f"Content {i}",
                confidence=0.5,
                status="active",
            )
            for i in range(3)
        ]
        db_session.add_all([doc] + concepts)
        db_session.commit()

        result = update_all_confidences(db_session)
        assert result["total"] >= 3  # 至少包含我们创建的 3 个
        assert result["changed"] >= 0


class TestGetConfidenceSummary:
    """confidence 统计摘要测试。"""

    def test_summary(self, db_session):
        """统计各区间分布。"""
        doc = Document(doc_id="sum-001", title="统计", bank="general", status="active")
        concepts = [
            Concept(concept_id=f"sum-001/{i}", doc_id="sum-001", parent_idx=i,
                    title=f"C{i}", content="x", confidence=c, status="active")
            for i, c in enumerate([0.2, 0.5, 0.8])
        ]
        db_session.add_all([doc] + concepts)
        db_session.commit()

        result = get_confidence_summary(db_session)
        assert result["total"] >= 3  # 至少包含我们创建的
        assert result["avg"] > 0
        assert "high (>0.7)" in result["distribution"]
