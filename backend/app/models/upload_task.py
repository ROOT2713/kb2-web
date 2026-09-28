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

    @classmethod
    def cleanup_stale_inflight(cls, db_session, max_age_hours: int = 24) -> int:
        """把长期卡在非终态的 pending/processing 任务标记为 failed。

        2026-09-29 修复（清理作业盲区）：cleanup_old_tasks() 只删**终态**
        （done/failed）行，对非终态（pending/processing）**零覆盖**。后果：
        worker 在代码上线前就崩了、服务在处理中被杀、或任务入队后从未被
        取走 —— 这些行会**永久滞留**：/tasks 轮询永远显示"进行中"，
        真实积压被掩盖成正常排队。

        实证：18 行自 2026-09-18 08:28 滞留 11 天
        （15 pending 停在 queued 0.000 + 3 processing 停在 parsing 0.050）。

        Args:
            db_session: SQLAlchemy session.
            max_age_hours: 超过该时长仍未进入终态即判定为死任务。

        Returns:
            被标记为 failed 的行数。
        """
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_age_hours)
        n = db_session.query(cls).filter(
            cls.status.in_(["pending", "processing"]),
            cls.updated_at < cutoff,
        ).update(
            {
                "status": "failed",
                "error_message": (f"stale: 超过 {max_age_hours}h 未进入终态，"
                                  f"由清理作业自动标记失败（{now:%Y-%m-%d %H:%M:%S}Z）"),
                "updated_at": now,
            },
            synchronize_session=False,
        )
        db_session.commit()
        return n
