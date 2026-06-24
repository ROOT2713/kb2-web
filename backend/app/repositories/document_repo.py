"""Document repository — CRUD operations for document metadata.

Ported from: kb-web server.py save_meta/get_meta/get_all_meta/update_meta/delete_meta/find_by_hash
Uses SQLAlchemy 2.0 style (select() + db.execute).
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

from sqlalchemy import select, delete as sa_delete, text as sa_text
from sqlalchemy.orm import Session

from app.models.document import Document

logger = logging.getLogger(__name__)

# Default metadata returned when document not found (matches v1 get_meta fallback)
_MISSING_META = {
    "title": "未知文档",
    "category": "",
    "filename": "未知",
    "created_at": "",
}


class DocumentRepository:
    """Repository for Document (doc_meta) metadata operations."""

    def __init__(self, db: Session):
        self.db = db

    # ── save ────────────────────────────────────────────────────
    def save(
        self,
        doc_id: str,
        title: str,
        category: str = "",
        filename: str = "",
        content_hash: str = "",
        doc_type: str = "generic",
        bank: str = "general",
        hs_bank: str = "kb_general",
        source: str = "manual",
        published_date=None,
        geo_scope: str = None,
        searchable: int = 0,
        coverage_pct: float = 0.0,
        original_text_length: int = 0,
    ) -> Document:
        """Insert or replace document metadata (matches v1 save_meta)."""
        doc = self.get(doc_id)
        if doc:
            # Update existing
            doc.title = title
            doc.category = category
            doc.filename = filename
            doc.content_hash = content_hash
            doc.doc_type = doc_type
            doc.bank = bank
            doc.hs_bank = hs_bank
            doc.source = source
            if published_date is not None:
                doc.published_date = published_date
            if geo_scope is not None:
                doc.geo_scope = geo_scope
            doc.searchable = searchable
            doc.coverage_pct = coverage_pct
            doc.original_text_length = original_text_length
            doc.updated_at = datetime.now(timezone.utc)
        else:
            # Insert new
            doc = Document(
                doc_id=doc_id,
                title=title,
                category=category,
                filename=filename,
                content_hash=content_hash,
                doc_type=doc_type,
                bank=bank,
                hs_bank=hs_bank,
                source=source,
                searchable=searchable,
                coverage_pct=coverage_pct,
                original_text_length=original_text_length,
                published_date=published_date,
                geo_scope=geo_scope,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            self.db.add(doc)

        self.db.commit()
        self.db.refresh(doc)
        logger.info("Document saved: doc_id=%s title=%s bank=%s", doc_id, title, bank)
        return doc

    # ── get ─────────────────────────────────────────────────────
    def get(self, doc_id: str) -> Optional[Document]:
        """Get document by doc_id. Returns None if not found."""
        stmt = select(Document).where(Document.doc_id == doc_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_meta(self, doc_id: str) -> dict:
        """Get document metadata as dict (matches v1 get_meta).

        Returns default dict with '未知文档' etc. when not found.
        """
        doc = self.get(doc_id)
        if doc is None:
            return dict(_MISSING_META)
        return {
            "title": doc.title,
            "category": doc.category,
            "filename": doc.filename,
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "bank": doc.bank,
            "doc_type": doc.doc_type,
            "content_hash": doc.content_hash,
            "hs_bank": doc.hs_bank,
            "searchable": doc.searchable if doc.searchable is not None else 0,
            "coverage_pct": doc.coverage_pct if doc.coverage_pct is not None else 0,
            "source": doc.source,
            "published_date": doc.published_date.isoformat() if doc.published_date else None,
            "geo_scope": doc.geo_scope,
        }

    # ── get_by_hash ────────────────────────────────────────────
    def get_by_hash(self, content_hash: str) -> Optional[Document]:
        """Find document by content hash (matches v1 find_by_hash).

        Excludes documents with empty hash or bank='skip'.
        """
        if not content_hash:
            return None
        stmt = (
            select(Document)
            .where(
                Document.content_hash == content_hash,
                Document.content_hash != "",
                Document.bank != "skip",
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    # ── list_all ────────────────────────────────────────────────
    def list_all(self, bank: str = "all") -> List[Document]:
        """List all documents, optionally filtered by bank.

        Matches v1 get_all_meta() behavior: excludes bank='skip'.
        """
        stmt = select(Document).where(Document.bank != "skip")
        if bank != "all":
            stmt = stmt.where(Document.bank == bank)
        stmt = stmt.order_by(Document.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def get_all_meta(self) -> Dict[str, dict]:
        """Return {doc_id: {...}} metadata dict (matches v1 get_all_meta)."""
        docs = self.list_all()
        result: Dict[str, dict] = {}
        for doc in docs:
            result[doc.doc_id] = {
                "title": doc.title,
                "category": doc.category,
                "filename": doc.filename,
                "created_at": doc.created_at.isoformat() if doc.created_at else "",
            }
        return result

    # ── update ──────────────────────────────────────────────────
    def update(self, doc_id: str, title: Optional[str] = None, category: Optional[str] = None) -> Optional[Document]:
        """Update document title and/or category (matches v1 update_meta).

        Only updates fields that are explicitly provided (not None).
        """
        doc = self.get(doc_id)
        if doc is None:
            logger.warning("Document not found for update: doc_id=%s", doc_id)
            return None

        updated = False
        if title is not None:
            doc.title = title
            updated = True
        if category is not None:
            doc.category = category
            updated = True

        if updated:
            doc.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(doc)
            logger.info("Document updated: doc_id=%s title=%s category=%s", doc_id, title, category)

        return doc

    # ── delete ──────────────────────────────────────────────────
    def delete(self, doc_id: str) -> bool:
        """Delete document and ALL its dependent rows (parent_chunks, concepts,
        kg_triples, concept_contradictions). Wraps in transaction; rolls back on
        any error to avoid half-cleaned state.

        Returns True if the document row was deleted.
        """
        doc = self.get(doc_id)
        if doc is None:
            logger.warning("Document not found for delete: doc_id=%s", doc_id)
            return False

        try:
            # concept_contradictions (二跳：通过 concepts 关联 doc_id)
            cc_res = self.db.execute(
                sa_text(
                    "DELETE FROM concept_contradictions "
                    "WHERE concept_a_id IN (SELECT concept_id FROM concepts WHERE doc_id=:d) "
                    "OR concept_b_id IN (SELECT concept_id FROM concepts WHERE doc_id=:d)"
                ),
                {"d": doc_id},
            )
            # kg_triples
            kg_res = self.db.execute(
                sa_text("DELETE FROM kg_triples WHERE doc_id=:d"), {"d": doc_id}
            )
            # concepts
            cp_res = self.db.execute(
                sa_text("DELETE FROM concepts WHERE doc_id=:d"), {"d": doc_id}
            )
            # parent_chunks
            pc_res = self.db.execute(
                sa_text("DELETE FROM parent_chunks WHERE doc_id=:d"), {"d": doc_id}
            )
            # 最后删 documents 主行
            self.db.delete(doc)
            self.db.commit()
            logger.info(
                "Document deleted (cascade): doc_id=%s | parent_chunks=%d concepts=%d kg_triples=%d cc_pairs=%d",
                doc_id,
                pc_res.rowcount or 0,
                cp_res.rowcount or 0,
                kg_res.rowcount or 0,
                cc_res.rowcount or 0,
            )
            return True
        except Exception as e:
            self.db.rollback()
            logger.error("Document delete failed (rolled back): doc_id=%s err=%s", doc_id, e)
            raise

    def delete_by_ids(self, doc_ids: list[str]) -> int:
        """Bulk delete documents by IDs. Returns count of deleted rows."""
        if not doc_ids:
            return 0
        stmt = sa_delete(Document).where(Document.doc_id.in_(doc_ids))
        result = self.db.execute(stmt)
        self.db.commit()
        count = result.rowcount
        if count:
            logger.info("Bulk deleted %d documents: %s", count, doc_ids)
        return count
