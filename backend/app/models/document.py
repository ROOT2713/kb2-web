"""Document metadata model + parent_chunks + concepts.

Replaces: kb-web server.py doc_meta SQLite table + save_meta/get_meta/update_meta/delete_meta
OKF lifecycle: concept_id, domain, confidence, status, superseded_by (P0 2026-06-21)
"""

from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Integer, Float, ForeignKey, Index
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

    # --- OKF lifecycle fields (P0 2026-06-21) ---
    concept_id = Column(String, nullable=True, index=True)   # e.g. "standards/security/gb-50116"
    domain = Column(String, nullable=True, index=True)        # top-level: standards|governance|methodology|operations|learning|ephemeral
    subdomain = Column(String, nullable=True)                 # e.g. "security", "laboratory"
    profile_confidence = Column(Float, nullable=True)         # from profile_document(), 0.0-1.0
    status = Column(String, default="active", index=True)     # active|draft|deprecated|superseded|stale
    superseded_by = Column(String, nullable=True, index=True) # doc_id of the version that replaced this one
    supersedes = Column(String, nullable=True)                # doc_id that this version replaced
    stale_at = Column(DateTime, nullable=True)                # when marked stale
    stale_reason = Column(String, nullable=True)              # why stale
    review_required = Column(Integer, default=0)              # 0=no review needed, 1=review recommended (confidence < 0.7)
    last_confirmed = Column(DateTime, nullable=True)          # last time knowledge was confirmed
    version = Column(String, default="1.0.0")                 # document version
    source_url = Column(String, nullable=True)                # original source URL
    chunk_count = Column(Integer, default=0)                  # total chunks (denormalized for fast query)

    __table_args__ = (
        Index("ix_documents_domain_status", "domain", "status"),
    )

    def to_dict(self) -> dict:
        d = {
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
        # OKF fields (only if set)
        for attr in ("concept_id", "domain", "subdomain", "profile_confidence",
                      "status", "superseded_by", "supersedes", "stale_at",
                      "stale_reason", "review_required", "last_confirmed",
                      "version", "source_url", "chunk_count"):
            val = getattr(self, attr)
            if val is not None:
                if isinstance(val, datetime):
                    d[attr] = val.isoformat()
                else:
                    d[attr] = val
        return d


class ParentChunk(Base):
    """Parent-level chunks for document re-construction (hierarchical chunking)."""
    __tablename__ = "parent_chunks"

    doc_id = Column(String, primary_key=True)
    parent_idx = Column(Integer, primary_key=True)
    parent_text = Column(Text, default="")
