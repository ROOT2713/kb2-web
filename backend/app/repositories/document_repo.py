"""Document repository — CRUD operations for document metadata.

Ported from: kb-web server.py save_meta/get_meta/get_all_meta/update_meta/delete_meta/find_by_hash
Uses SQLAlchemy 2.0 style (select() + db.execute).
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

from sqlalchemy import select, delete as sa_delete
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
        """Delete document metadata (matches v1 delete_meta).

        Returns True if a row was deleted.
        """
        doc = self.get(doc_id)
        if doc is None:
            logger.warning("Document not found for delete: doc_id=%s", doc_id)
            return False

        self.db.delete(doc)
        self.db.commit()
        logger.info("Document deleted: doc_id=%s", doc_id)
        return True

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
