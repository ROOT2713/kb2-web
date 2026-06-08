"""Document metadata model + parent_chunks.

Replaces: kb-web server.py doc_meta SQLite table + save_meta/get_meta/update_meta/delete_meta
"""

from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Integer, Float
from app.models.database import Base


class Document(Base):
    __tablename__ = "documents"

    doc_id = Column(String, primary_key=True)
    title = Column(String, nullable=False, default="")
    category = Column(String, default="")
    filename = Column(String, default="")
    content_hash = Column(String, default="")
    doc_type = Column(String, default="generic")
    bank = Column(String, default="general", index=True)
    hs_bank = Column(String, default="kb_general")
    source = Column(String, default="manual")
    searchable = Column(Integer, default=0)
    coverage_pct = Column(Float, default=0.0)
    verified_at = Column(DateTime, nullable=True)
    original_text_length = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "category": self.category,
            "filename": self.filename,
            "content_hash": self.content_hash,
            "doc_type": self.doc_type,
            "bank": self.bank,
            "source": self.source,
            "searchable": self.searchable,
            "coverage_pct": self.coverage_pct,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ParentChunk(Base):
    """Parent-level chunks for document re-construction (hierarchical chunking)."""
    __tablename__ = "parent_chunks"

    doc_id = Column(String, primary_key=True)
    parent_idx = Column(Integer, primary_key=True)
    parent_text = Column(Text, default="")
