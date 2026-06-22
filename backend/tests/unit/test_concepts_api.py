"""Tests for app.api.concepts — GET /{concept_id}, GET /search, GET /list."""

import pytest
from app.models.concept import Concept


# ═══════════════════════════════════════════════════════
# Helper: insert test concepts
# ═══════════════════════════════════════════════════════

def _insert_test_concepts(db_session):
    """Insert sample concepts for testing."""
    # Clear existing concepts first
    db_session.query(Concept).delete()
    db_session.commit()

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
            concept_id="methodology/ai-practice/guide/clause-1",
            doc_id="doc-002",
            parent_idx=0,
            title="AI 应用实践概述",
            summary="人工智能在政务领域的应用实践",
            content="人工智能技术在政务信息化中的应用越来越广泛。" * 10,
            confidence=0.6,
            status="active",
            access_count=1,
        ),
        Concept(
            concept_id="standards/old-standard/clause-1",
            doc_id="doc-003",
            parent_idx=0,
            title="旧标准条款",
            summary="已废弃的标准",
            content="本标准已被新版本替代。" * 10,
            confidence=0.3,
            status="deprecated",
            access_count=0,
        ),
    ]
    for c in concepts:
        db_session.merge(c)
    db_session.commit()


# ═══════════════════════════════════════════════════════
# GET /api/concepts/{concept_id}
# ═══════════════════════════════════════════════════════

class TestGetConcept:
    def test_get_existing_concept(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """获取存在的 concept"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts/get", params={"concept_id": "standards/security/gb-50116/clause-4.1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["concept_id"] == "standards/security/gb-50116/clause-4.1"
        assert data["title"] == "4.1 一般规定"
        assert data["confidence"] == 0.8
        assert "content" in data  # full content in to_full_dict

    def test_get_nonexistent_concept(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """获取不存在的 concept → 404"""
        resp = client.get("/api/concepts/get", params={"concept_id": "nonexistent/id"})
        assert resp.status_code == 404

    def test_access_count_increments(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """访问后 access_count 递增"""
        _insert_test_concepts(db_session)
        # First access
        client.get("/api/concepts/get", params={"concept_id": "standards/security/gb-50116/clause-4.1"})
        # Second access
        resp = client.get("/api/concepts/get", params={"concept_id": "standards/security/gb-50116/clause-4.1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_count"] >= 6  # initial 5 + 2 accesses


# ═══════════════════════════════════════════════════════
# GET /api/concepts/search
# ═══════════════════════════════════════════════════════

class TestSearchConcepts:
    def test_search_by_keyword(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """关键词搜索"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts/search", params={"q": "火灾"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2  # 两个 GB-50116 concept 都包含"火灾"

    def test_search_by_summary(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """搜索摘要内容"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts/search", params={"q": "人工智能"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_search_filter_by_doc(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按 doc_id 过滤"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts/search", params={"q": "标准", "doc_id": "doc-001"})
        assert resp.status_code == 200
        data = resp.json()
        for c in data["concepts"]:
            assert c["doc_id"] == "doc-001"

    def test_search_excludes_deprecated(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """默认排除 deprecated 状态"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts/search", params={"q": "标准"})
        assert resp.status_code == 200
        data = resp.json()
        for c in data["concepts"]:
            assert c["status"] != "deprecated"

    def test_search_empty_query(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """空查询 → 422"""
        resp = client.get("/api/concepts/search", params={"q": ""})
        assert resp.status_code == 422

    def test_search_no_results(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """无匹配结果"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts/search", params={"q": "完全不匹配的内容xyz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["concepts"] == []


# ═══════════════════════════════════════════════════════
# GET /api/concepts
# ═══════════════════════════════════════════════════════

class TestListConcepts:
    def test_list_all_active(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """列出所有 active concepts"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3  # 3 active, 1 deprecated

    def test_list_filter_by_doc(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按 doc_id 过滤"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts", params={"doc_id": "doc-001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_list_filter_by_domain(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """按 domain 前缀过滤"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts", params={"domain": "standards"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # 2 active standards concepts

    def test_list_pagination(self, client, db_session, mock_hindsight, mock_get_active_banks):
        """分页"""
        _insert_test_concepts(db_session)
        resp = client.get("/api/concepts", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["concepts"]) == 2
        assert data["total"] == 3
