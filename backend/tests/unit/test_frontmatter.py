"""Tests for app.services.frontmatter - YAML frontmatter export (Phase B #4)."""

import pytest
import yaml
from datetime import datetime, timezone

from app.services.frontmatter import concept_to_frontmatter, _yaml_str
from app.models.document import Document
from app.models.concept import Concept, KGTriple


class TestYamlStr:
    """Unit tests for _yaml_str helper."""

    def test_empty_string(self):
        assert _yaml_str("") == '""'

    def test_simple_string(self):
        assert _yaml_str("hello_world") == "hello_world"

    def test_string_with_colon(self):
        result = _yaml_str("key: value")
        assert result.startswith('"') and result.endswith('"')

    def test_string_with_quote(self):
        result = _yaml_str('say "hello"')
        assert result.startswith('"') and '\\"' in result


class TestConceptToFrontmatter:
    """Integration tests for concept_to_frontmatter."""

    def test_basic_frontmatter(self, db_session):
        """Basic concept with all fields produces valid YAML frontmatter."""
        doc = Document(
            doc_id="fm-doc-001",
            title="测试文档",
            bank="general",
            doc_type="regulation",
            domain="governance",
            subdomain="privacy",
            last_confirmed=datetime(2026, 1, 15, tzinfo=timezone.utc),
            review_required=0,
            status="active",
        )
        concept = Concept(
            concept_id="governance/privacy/doc-001/clause-1",
            doc_id="fm-doc-001",
            parent_idx=0,
            title="个人信息保护条款",
            content="收集个人信息应当遵循合法、正当、必要原则。",
            status="active",
            confidence=0.85,
        )
        db_session.add_all([doc, concept])
        db_session.commit()

        result = concept_to_frontmatter(db_session, "governance/privacy/doc-001/clause-1")
        assert result is not None
        assert result.startswith("---")
        assert "concept_id:" in result
        assert "governance/privacy/doc-001/clause-1" in result
        assert "doc_id: fm-doc-001" in result
        assert "title:" in result
        assert "type: regulation" in result
        assert "status: active" in result
        assert "confidence: 0.850" in result
        assert "last_confirmed: 2026-01-15" in result
        assert "review_required: false" in result
        assert "source_count: 1" in result
        assert "contradiction_count: 0" in result
        assert "domain: governance" in result
        assert "subdomain: privacy" in result
        assert "sources:" in result
        assert "related:" in result
        assert "收集个人信息应当" in result

    def test_yaml_parseable(self, db_session):
        """Output must be parseable YAML in the header block."""
        doc = Document(
            doc_id="fm-doc-002",
            title="标准测试",
            bank="standard",
            doc_type="gb_standard",
            domain="standards",
            subdomain="security",
            last_confirmed=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        concept = Concept(
            concept_id="standards/security/doc-002/clause-1",
            doc_id="fm-doc-002",
            parent_idx=0,
            title="Chapter 1",
            content="This is test content.",
            status="active",
            confidence=0.92,
        )
        db_session.add_all([doc, concept])
        db_session.commit()

        result = concept_to_frontmatter(db_session, "standards/security/doc-002/clause-1")
        assert result is not None

        # Extract YAML header (between first --- and second ---)
        parts = result.split("---", 2)
        assert len(parts) >= 3
        yaml_header = parts[1]
        parsed = yaml.safe_load(yaml_header)
        assert parsed is not None
        assert parsed["concept_id"] == "standards/security/doc-002/clause-1"
        assert parsed["type"] == "gb_standard"
        assert parsed["confidence"] == 0.92
        assert parsed["source_count"] == 1
        assert parsed["contradiction_count"] == 0
        assert parsed["domain"] == "standards"
        assert isinstance(parsed["sources"], list)
        assert isinstance(parsed["related"], list)

    def test_nonexistent_concept(self, db_session):
        """Nonexistent concept returns None."""
        result = concept_to_frontmatter(db_session, "nonexistent/id")
        assert result is None

    def test_frontmatter_with_related_edges(self, db_session):
        """Frontmatter includes related edges from KGTriple table."""
        doc = Document(
            doc_id="fm-doc-003",
            title="Related Doc",
            bank="general",
            doc_type="generic",
            domain="methodology",
            subdomain="testing",
        )
        concept = Concept(
            concept_id="methodology/testing/doc-003/clause-1",
            doc_id="fm-doc-003",
            parent_idx=0,
            title="Test Clause",
            content="Some content here.",
            status="active",
            confidence=0.75,
        )
        triple = KGTriple(
            subject_type="concept",
            subject_id="methodology/testing/doc-003/clause-1",
            predicate="references",
            object_type="concept",
            object_id="other/concept/id",
            doc_id="fm-doc-003",
            confidence=0.9,
        )
        db_session.add_all([doc, concept, triple])
        db_session.commit()

        result = concept_to_frontmatter(db_session, "methodology/testing/doc-003/clause-1")
        assert result is not None
        assert "predicate: references" in result
        assert "other/concept/id" in result

    def test_frontmatter_minimal_doc(self, db_session):
        """Minimal document (missing doc fields) still produces valid output."""
        concept = Concept(
            concept_id="minimal/concept-1",
            doc_id="minimal-doc-1",
            parent_idx=0,
            title="Minimal",
            content="Minimal content.",
            status="active",
            confidence=0.5,
        )
        # No Document row - simulate missing doc
        db_session.add(concept)
        db_session.commit()

        result = concept_to_frontmatter(db_session, "minimal/concept-1")
        assert result is not None
        assert "type: generic" in result
        assert "last_confirmed: null" in result
        assert "domain: unknown" in result
        assert "review_required: false" in result
