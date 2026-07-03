"""Upload task state model — async upload job tracking.

Tracks background upload processing stages so the frontend can poll progress
without blocking the HTTP request.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Float

from app.models.database import Base


class UploadTask(Base):
    """Persistent state for async document upload tasks."""
    __tablename__ = "upload_tasks"

    id = Column(String, primary_key=True)                           # UUID
    status = Column(String, default="pending", nullable=False)      # pending / processing / done / failed
    filename = Column(String, default="", nullable=False)
    progress = Column(Float, default=0.0, nullable=False)           # 0.0 – 1.0
    stage = Column(String, default="", nullable=False)              # e.g. "parsing", "chunking", "hindsight"
    error_message = Column(Text, nullable=True)                     # failure reason
    result_doc_id = Column(String, nullable=True)                   # doc_id on success
    result = Column(Text, nullable=True)                            # JSON response for frontend
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    @classmethod
    def cleanup_old_tasks(cls, db_session, max_age_days: int = 30) -> int:
        """Delete completed or failed tasks older than max_age_days.

        Args:
            db_session: SQLAlchemy session.
            max_age_days: Maximum age in days before a completed/failed task is deleted.

        Returns:
            Number of deleted tasks.
        """
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        deleted = db_session.query(cls).filter(
            cls.status.in_(["done", "failed"]),
            cls.updated_at < cutoff,
        ).delete(synchronize_session=False)
        db_session.commit()
        return deleted
