"""Tests for app.services.contradiction — embedding-based contradiction detection (Phase B #3)."""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from app.services.contradiction import (
    compute_contradiction_score,
    _cosine_similarity,
    CONTRADICTION_THRESHOLD,
)
from app.models.concept import Concept
from app.models.document import Document


class TestCosineSimilarity:
    """Unit tests for cosine similarity computation."""

    def test_identical_vectors(self):
        a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        b = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(1.0, abs=0.001)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(0.0, abs=0.001)

    def test_opposite_vectors(self):
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([-1.0, -2.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == pytest.approx(-1.0, abs=0.001)

    def test_zero_vector(self):
        a = np.array([0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 2.0], dtype=np.float32)
        assert _cosine_similarity(a, b) == 0.0


class TestComputeContradictionScore:
    """Integration tests for compute_contradiction_score."""

    def test_no_siblings_returns_one(self, db_session):
        """No sibling concepts → contradiction score = 1.0."""
        concept = Concept(
            concept_id="test/domain/concept-1",
            doc_id="doc-1",
            parent_idx=0,
            title="Test Concept",
            content="This is test content for the concept.",
            status="active",
            confidence=0.5,
        )
        db_session.add(concept)
        db_session.commit()

        score = compute_contradiction_score(db_session, concept)
        assert score == 1.0

    def test_short_concept_id_returns_one(self, db_session):
        """Concept ID too short to extract prefix → returns 1.0."""
        concept = Concept(
            concept_id="singlepart",
            doc_id="doc-1",
            parent_idx=0,
            title="Short",
            content="Some content here.",
            status="active",
        )
        db_session.add(concept)
        db_session.commit()

        score = compute_contradiction_score(db_session, concept)
        assert score == 1.0

    def test_fallback_on_no_embedding(self, db_session):
        """When embedding API fails, return 1.0 (degradation)."""
        concept = Concept(
            concept_id="test/domain/concept-fallback",
            doc_id="doc-1",
            parent_idx=0,
            title="Fallback",
            content="",  # Empty content → cannot embed
            status="active",
        )
        db_session.add(concept)
        db_session.commit()

        score = compute_contradiction_score(db_session, concept)
        assert score == 1.0

    @patch("app.services.contradiction.get_embedding")
    def test_high_similarity_no_contradiction(self, mock_get_embedding, db_session):
        """When siblings are semantically similar, no contradiction detected."""
        # Create two concepts in same domain
        c1 = Concept(
            concept_id="test/domain/concept-a",
            doc_id="doc-a",
            parent_idx=0,
            title="Concept A",
            content="Information security is important for organizations.",
            status="active",
            confidence=0.5,
        )
        c2 = Concept(
            concept_id="test/domain/concept-b",
            doc_id="doc-b",
            parent_idx=0,
            title="Concept B",
            content="Organizations need strong information security measures.",
            status="active",
            confidence=0.5,
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        # Mock embeddings: similar vectors (cosine ~0.99)
        async def fake_embedding(text):
            if "Concept A" in text:
                return np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
            else:
                return np.array([0.5, 0.5, 0.5, 0.51], dtype=np.float32)

        mock_get_embedding.side_effect = fake_embedding

        score = compute_contradiction_score(db_session, c1)
        assert score == 1.0  # No contradiction (similarity > 0.3)

    @patch("app.services.contradiction.get_embedding")
    def test_low_similarity_contradiction_detected(self, mock_get_embedding, db_session):
        """When siblings are semantically opposite, contradiction is detected."""
        c1 = Concept(
            concept_id="test/domain/concept-x",
            doc_id="doc-x",
            parent_idx=0,
            title="Pro Encryption",
            content="Encryption should be mandatory for all data.",
            status="active",
            confidence=0.5,
        )
        c2 = Concept(
            concept_id="test/domain/concept-y",
            doc_id="doc-y",
            parent_idx=0,
            title="Anti Encryption",
            content="Encryption should never be required for public data.",
            status="active",
            confidence=0.5,
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        # Mock embeddings: opposite vectors (cosine ~ -1.0)
        async def fake_embedding(text):
            if "mandatory" in text:
                return np.array([1.0, 1.0, 1.0], dtype=np.float32)
            else:
                return np.array([-1.0, -1.0, -1.0], dtype=np.float32)

        mock_get_embedding.side_effect = fake_embedding

        score = compute_contradiction_score(db_session, c1)
        # min_sim should be ~ -1.0, which is < 0.3 threshold
        assert score < CONTRADICTION_THRESHOLD
        assert score < 0.5  # Strongly contradictory

    @patch("app.services.contradiction.get_embedding")
    def test_multiple_siblings_min_used(self, mock_get_embedding, db_session):
        """Among multiple siblings, the minimum similarity is used."""
        c1 = Concept(
            concept_id="test/domain/concept-main",
            doc_id="doc-main",
            parent_idx=0,
            title="Main Concept",
            content="Data retention policy basics.",
            status="active",
            confidence=0.5,
        )
        # Create several siblings
        siblings = []
        for i in range(7):
            siblings.append(Concept(
                concept_id=f"test/domain/concept-sib-{i}",
                doc_id=f"doc-sib-{i}",
                parent_idx=0,
                title=f"Sibling {i}",
                content=f"Content for sibling {i} about related topics.",
                status="active",
                confidence=0.5,
            ))
        db_session.add_all([c1] + siblings)
        db_session.commit()

        # Mock: target is [1,0,0]; siblings are various
        call_count = [0]

        async def fake_embedding(text):
            call_count[0] += 1
            if "Main" in text or "main" in text:
                return np.array([1.0, 0.0, 0.0], dtype=np.float32)
            idx = call_count[0] - 2  # 0-based sibling index
            # Make one sibling strongly contradictory (negative similarity)
            if idx == 3:
                return np.array([-1.0, 0.0, 0.0], dtype=np.float32)
            # Others are similar
            return np.array([0.9, 0.1 * idx, 0.0], dtype=np.float32)

        mock_get_embedding.side_effect = fake_embedding

        score = compute_contradiction_score(db_session, c1)
        # Should find the contradictory sibling and return low score
        assert score < CONTRADICTION_THRESHOLD
