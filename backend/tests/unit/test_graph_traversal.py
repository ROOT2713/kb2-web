"""Tests for app.services.graph_traversal — KG BFS traversal (Phase B #5)."""

import pytest

from app.services.graph_traversal import traverse_kg, get_kg_context_for_query
from app.models.document import Document
from app.models.concept import Concept, KGTriple


class TestTraverseKG:
    """Unit tests for traverse_kg BFS traversal."""

    def test_empty_seeds(self, db_session):
        """Empty seed list returns empty result."""
        result = traverse_kg(db_session, [], max_depth=2, max_nodes=10)
        assert result == []

    def test_no_kg_edges(self, db_session):
        """No KG edges → empty result."""
        doc = Document(
            doc_id="gt-doc-001",
            title="Test Doc",
            bank="general",
            status="active",
        )
        db_session.add(doc)
        db_session.commit()

        result = traverse_kg(db_session, ["gt-doc-001"], max_depth=2, max_nodes=10)
        assert result == []

    def test_single_hop_traversal(self, db_session):
        """Single hop traversal along a 'cites' edge."""
        doc_a = Document(doc_id="gt-doc-A", title="Doc A", bank="general", status="active")
        doc_b = Document(doc_id="gt-doc-B", title="Doc B", bank="general", status="active")

        concept_a = Concept(
            concept_id="gt-doc-A/clause-1",
            doc_id="gt-doc-A",
            parent_idx=0,
            title="A-1",
            content="Content A",
            status="active",
        )
        concept_b = Concept(
            concept_id="gt-doc-B/clause-1",
            doc_id="gt-doc-B",
            parent_idx=0,
            title="B-1",
            content="Content B",
            status="active",
        )

        triple = KGTriple(
            subject_type="document",
            subject_id="gt-doc-A",
            predicate="cites",
            object_type="document",
            object_id="gt-doc-B",
            doc_id="gt-doc-A",
            confidence=0.9,
        )

        db_session.add_all([doc_a, doc_b, concept_a, concept_b, triple])
        db_session.commit()

        result = traverse_kg(db_session, ["gt-doc-A"], max_depth=2, max_nodes=10)
        assert len(result) == 1
        assert result[0]["predicate"] == "cites"
        assert result[0]["depth"] == 1
        assert result[0]["confidence"] == 0.9

    def test_two_hop_chain(self, db_session):
        """Two-hop BFS: A → B → C, verify BFS finds C at depth 2."""
        # Create chain: gt-chain-A → gt-chain-B → gt-chain-C
        doc_a = Document(doc_id="gt-chain-A", title="A", bank="general", status="active")
        doc_b = Document(doc_id="gt-chain-B", title="B", bank="general", status="active")
        doc_c = Document(doc_id="gt-chain-C", title="C", bank="general", status="active")

        concept_a = Concept(concept_id="gt-chain-A/c-1", doc_id="gt-chain-A", parent_idx=0,
                            title="A1", content="A", status="active")
        concept_b = Concept(concept_id="gt-chain-B/c-1", doc_id="gt-chain-B", parent_idx=0,
                            title="B1", content="B", status="active")
        concept_c = Concept(concept_id="gt-chain-C/c-1", doc_id="gt-chain-C", parent_idx=0,
                            title="C1", content="C", status="active")

        triple_ab = KGTriple(subject_type="document", subject_id="gt-chain-A",
                             predicate="references", object_type="document",
                             object_id="gt-chain-B", doc_id="gt-chain-A", confidence=1.0)
        triple_bc = KGTriple(subject_type="document", subject_id="gt-chain-B",
                             predicate="cites", object_type="document",
                             object_id="gt-chain-C", doc_id="gt-chain-B", confidence=0.8)

        db_session.add_all([doc_a, doc_b, doc_c, concept_a, concept_b, concept_c,
                           triple_ab, triple_bc])
        db_session.commit()

        result = traverse_kg(db_session, ["gt-chain-A"], max_depth=2, max_nodes=10)
        assert len(result) == 2
        depths = {r["doc_id"]: r["depth"] for r in result}
        assert depths.get("gt-chain-B") == 1
        assert depths.get("gt-chain-C") == 2

    def test_max_nodes_limit(self, db_session):
        """Respects max_nodes limit."""
        doc_main = Document(doc_id="gt-main", title="Main", bank="general", status="active")

        entities = [doc_main]
        for i in range(15):
            did = f"gt-branch-{i}"
            entities.append(Document(doc_id=did, title=f"Branch {i}", bank="general", status="active"))
            entities.append(Concept(concept_id=f"{did}/c-1", doc_id=did, parent_idx=0,
                                    title=f"B{i}", content="x", status="active"))
            entities.append(KGTriple(subject_type="document", subject_id="gt-main",
                                     predicate="references", object_type="document",
                                     object_id=did, doc_id="gt-main", confidence=0.5))

        db_session.add_all(entities)
        db_session.commit()

        result = traverse_kg(db_session, ["gt-main"], max_depth=2, max_nodes=5)
        assert len(result) <= 5

    def test_bidirectional_edges(self, db_session):
        """Edges in both directions (subject→object and object→subject) are traversed."""
        doc_x = Document(doc_id="gt-bidir-X", title="X", bank="general", status="active")
        doc_y = Document(doc_id="gt-bidir-Y", title="Y", bank="general", status="active")

        concept_x = Concept(concept_id="gt-bidir-X/c-1", doc_id="gt-bidir-X", parent_idx=0,
                           title="X", content="X", status="active")
        concept_y = Concept(concept_id="gt-bidir-Y/c-1", doc_id="gt-bidir-Y", parent_idx=0,
                           title="Y", content="Y", status="active")

        # Y references X (subject=Y, object=X)
        triple = KGTriple(subject_type="document", subject_id="gt-bidir-Y",
                         predicate="supersedes", object_type="document",
                         object_id="gt-bidir-X", doc_id="gt-bidir-Y", confidence=1.0)

        db_session.add_all([doc_x, doc_y, concept_x, concept_y, triple])
        db_session.commit()

        # Seed from X — should find Y because X is object in the triple
        result = traverse_kg(db_session, ["gt-bidir-X"], max_depth=1, max_nodes=10)
        assert len(result) == 1
        assert result[0]["predicate"] == "supersedes"

    def test_visited_deduplication(self, db_session):
        """Same node reached via multiple paths is only reported once."""
        doc_s = Document(doc_id="gt-visit-S", title="S", bank="general", status="active")
        doc_t = Document(doc_id="gt-visit-T", title="T", bank="general", status="active")

        concept_s = Concept(concept_id="gt-visit-S/c-1", doc_id="gt-visit-S", parent_idx=0,
                           title="S", content="S", status="active")
        concept_t = Concept(concept_id="gt-visit-T/c-1", doc_id="gt-visit-T", parent_idx=0,
                           title="T", content="T", status="active")

        triple1 = KGTriple(subject_type="document", subject_id="gt-visit-S",
                          predicate="cites", object_type="document",
                          object_id="gt-visit-T", doc_id="gt-visit-S", confidence=1.0)
        triple2 = KGTriple(subject_type="document", subject_id="gt-visit-S",
                          predicate="references", object_type="document",
                          object_id="gt-visit-T", doc_id="gt-visit-S", confidence=0.9)

        db_session.add_all([doc_s, doc_t, concept_s, concept_t, triple1, triple2])
        db_session.commit()

        result = traverse_kg(db_session, ["gt-visit-S"], max_depth=1, max_nodes=10)
        # T should only appear once despite 2 edges
        t_entries = [r for r in result if "gt-visit-T" in r["doc_id"]]
        assert len(t_entries) <= 1


class TestGetKGContextForQuery:
    """Integration tests for get_kg_context_for_query."""

    def test_returns_structured_and_text(self, db_session):
        """Returns both structured list and formatted text."""
        doc_a = Document(doc_id="kgctx-A", title="Doc A", bank="general", status="active")
        doc_b = Document(doc_id="kgctx-B", title="Doc B", bank="general", status="active")

        concept_a = Concept(concept_id="kgctx-A/c-1", doc_id="kgctx-A", parent_idx=0,
                           title="信息安全条款", content="关于信息安全的条款内容...",
                           summary="本条款规定了信息安全的基本要求。", status="active")
        concept_b = Concept(concept_id="kgctx-B/c-1", doc_id="kgctx-B", parent_idx=0,
                           title="网络安全条款", content="关于网络安全的条款内容...",
                           status="active")

        triple = KGTriple(subject_type="document", subject_id="kgctx-A",
                         predicate="references", object_type="document",
                         object_id="kgctx-B", doc_id="kgctx-A", confidence=0.95)

        db_session.add_all([doc_a, doc_b, concept_a, concept_b, triple])
        db_session.commit()

        kg_list, kg_text = get_kg_context_for_query(
            db_session, ["kgctx-A"], max_depth=2, max_nodes=10, max_chars=3000,
        )

        assert len(kg_list) >= 1
        assert kg_list[0]["predicate"] == "references"
        assert kg_list[0]["depth"] == 1
        assert len(kg_text) > 0
        # Should contain neighbor B's title or content (we traversed A → B)
        assert "网络安全" in kg_text or "Doc B" in kg_text
