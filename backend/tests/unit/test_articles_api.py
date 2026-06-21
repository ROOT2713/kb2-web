"""Tests for app.api.articles — POST /api/articles/extract, GET /api/articles/by-concept."""

import pytest
from app.models.concept import Concept
from app.models.document import Document


# ═══════════════════════════════════════════════════════
# Helper: insert test data
# ═══════════════════════════════════════════════════════

def _insert_test_data(db_session):
    """Insert sample documents and concepts for testing."""
    # Clear existing data
    db_session.query(Concept).delete()
    db_session.query(Document).delete()
    db_session.commit()

    # Insert documents
    docs = [
        Document(
            doc_id="doc-001",
            title="GB/T 50116-2013 火灾自动报警系统设计规范",
            bank="standard",
            domain="standards",
            status="active",
        ),
        Document(
            doc_id="doc-002",
            title="网络安全法",
            bank="law",
            domain="standards",
            status="active",
        ),
        Document(
            doc_id="doc-003",
            title="旧标准文档",
            bank="standard",
            domain="standards",
            status="deprecated",
        ),
    ]
    for d in docs:
        db_session.merge(d)

    # Insert concepts
    concepts = [
        Concept(
            concept_id="standards/security/gb-50116/clause-4.1",
            doc_id="doc-001",
            parent_idx=0,
            title="4.1 一般规定",
            summary="火灾自动报警系统的一般规定",
            content="火灾自动报警系统应设有自动和手动两种触发装置。" * 10,
            confidence=0.8,
            status="active",
            access_count=5,
        ),
        Concept(
            concept_id="standards/security/gb-50116/clause-5.2",
            doc_id="doc-001",
            parent_idx=1,
            title="5.2 系统设计",
            summary="火灾自动报警系统的设计要求",
            content="系统设计应符合国家现行有关标准的规定。" * 10,
            confidence=0.7,
            status="active",
            access_count=3,
        ),
        Concept(
            concept_id="standards/cyber/clause-1",
            doc_id="doc-002",
            parent_idx=0,
            title="网络安全保护",
            summary="网络空间安全管理",
            content="网络安全是国家安全的重要组成部分。" * 10,
            confidence=0.9,
            status="active",
            access_count=10,
        ),
        Concept(
            concept_id="standards/old/clause-1",
            doc_id="doc-003",
            parent_idx=0,
            title="旧标准条款",
            summary="已废弃的标准",
            content="本标准已被新版本替代。" * 10,
            confidence=0.3,
            status="active",
            access_count=0,
        ),
    ]
    for c in concepts:
        db_session.merge(c)
    db_session.commit()


# ═══════════════════════════════════════════════════════
# POST /api/articles/extract
# ═══════════════════════════════════════════════════════

class TestExtractByTopic:
    def test_extract_basic(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """基本提取"""
        _insert_test_data(db_session)
        resp = client.post("/api/articles/extract", json={"topic": "火灾"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "火灾"
        assert data["total_documents"] >= 1
        assert data["total_concepts"] >= 1

    def test_extract_aggregates_by_doc(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按文档聚合"""
        _insert_test_data(db_session)
        resp = client.post("/api/articles/extract", json={"topic": "火灾"})
        data = resp.json()
        # doc-001 有两个匹配的 concept，应该聚合到一个文档
        doc_ids = [r["doc_id"] for r in data["results"]]
        assert "doc-001" in doc_ids
        for r in data["results"]:
            if r["doc_id"] == "doc-001":
                assert r["concept_count"] == 2

    def test_extract_excludes_deprecated(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """默认排除 deprecated 文档"""
        _insert_test_data(db_session)
        resp = client.post("/api/articles/extract", json={"topic": "标准"})
        data = resp.json()
        doc_ids = [r["doc_id"] for r in data["results"]]
        assert "doc-003" not in doc_ids  # deprecated

    def test_extract_min_confidence(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按置信度过滤"""
        _insert_test_data(db_session)
        resp = client.post("/api/articles/extract", json={"topic": "火灾", "min_confidence": 0.75})
        data = resp.json()
        for r in data["results"]:
            assert r["confidence"] >= 0.75

    def test_extract_empty_topic(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """空主题"""
        resp = client.post("/api/articles/extract", json={"topic": ""})
        assert resp.status_code == 422  # validation error

    def test_extract_no_results(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """无匹配结果"""
        _insert_test_data(db_session)
        resp = client.post("/api/articles/extract", json={"topic": "完全不匹配xyz"})
        data = resp.json()
        assert data["total_documents"] == 0
        assert data["results"] == []

    def test_extract_sorted_by_confidence(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按置信度排序"""
        _insert_test_data(db_session)
        resp = client.post("/api/articles/extract", json={"topic": "安全"})
        data = resp.json()
        if len(data["results"]) >= 2:
            # 第一个应该比第二个置信度高
            assert data["results"][0]["confidence"] >= data["results"][1]["confidence"]


# ═══════════════════════════════════════════════════════
# GET /api/articles/by-concept
# ═══════════════════════════════════════════════════════

class TestExtractByConcept:
    def test_by_concept_prefix(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按 concept_id 前缀查询"""
        _insert_test_data(db_session)
        resp = client.get("/api/articles/by-concept", params={"concept_id": "standards/security"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] >= 1
        assert data["total_concepts"] >= 1

    def test_by_concept_no_match(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """无匹配"""
        _insert_test_data(db_session)
        resp = client.get("/api/articles/by-concept", params={"concept_id": "nonexistent"})
        data = resp.json()
        assert data["total_documents"] == 0
