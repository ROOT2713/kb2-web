"""Checkpoint manager — tracks ingestion pipeline progress for resume/retry.

每个任务经过上传→解析→切片→向量化→索引→概念生成等多个步骤。
如果进程中途崩溃，checkpoint 记录到哪一步了，可以用来恢复。
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

_STEPS = ["uploaded", "parsed", "chunked", "embedded", "indexed", "concept_generated"]


class CheckpointManager:
    """Manages job checkpoints in SQLite."""

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        try:
            db = SessionLocal()
            try:
                db.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS job_checkpoints ("
                        "  job_id TEXT PRIMARY KEY,"
                        "  doc_id TEXT,"
                        "  filename TEXT,"
                        "  step TEXT,"
                        "  step_data TEXT DEFAULT '{}',"
                        "  created_at TEXT,"
                        "  updated_at TEXT,"
                        "  status TEXT DEFAULT 'running',"
                        "  error TEXT DEFAULT ''"
                        ")"
                    )
                )
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error("Failed to create checkpoints table: %s", e)

    def create(self, doc_id: str, filename: str) -> str:
        """Create a new checkpoint job. Returns job_id."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            db = SessionLocal()
            try:
                db.execute(
                    text("INSERT INTO job_checkpoints (job_id, doc_id, filename, step, created_at, updated_at, status) "
                         "VALUES (:jd, :di, :fn, :st, :ca, :ua, :ss)"),
                    {"jd": job_id, "di": doc_id, "fn": filename, "st": "uploaded",
                     "ca": now, "ua": now, "ss": "running"}
                )
                db.commit()
                logger.info("Checkpoint created: %s for %s", job_id, filename)
                return job_id
            finally:
                db.close()
        except Exception as e:
            logger.error("Failed to create checkpoint: %s", e)
            return ""

    def save(self, job_id: str, step: str, step_data: dict = None):
        """Update checkpoint to a new step."""
        now = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(step_data or {}, ensure_ascii=False)
        try:
            db = SessionLocal()
            try:
                db.execute(
                    text("UPDATE job_checkpoints SET step=:st, step_data=:sd, updated_at=:ua WHERE job_id=:jd"),
                    {"st": step, "sd": data_json, "ua": now, "jd": job_id}
                )
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to save checkpoint %s: %s", job_id, e)

    def mark_failed(self, job_id: str, error: str):
        """Mark a job as failed with error message."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            db = SessionLocal()
            try:
                db.execute(
                    text("UPDATE job_checkpoints SET status='failed', error=:err, updated_at=:ua WHERE job_id=:jd"),
                    {"err": error[:500], "ua": now, "jd": job_id}
                )
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to mark checkpoint failed: %s", e)

    def mark_completed(self, job_id: str):
        """Mark a job as completed."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            db = SessionLocal()
            try:
                db.execute(
                    text("UPDATE job_checkpoints SET status='completed', step='concept_generated', updated_at=:ua WHERE job_id=:jd"),
                    {"ua": now, "jd": job_id}
                )
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to mark checkpoint completed: %s", e)

    def load(self, job_id: str) -> dict:
        """Load checkpoint for a job."""
        try:
            db = SessionLocal()
            try:
                row = db.execute(
                    text("SELECT * FROM job_checkpoints WHERE job_id=:jd"),
                    {"jd": job_id}
                ).fetchone()
                if not row:
                    return {}
                columns = row._mapping.keys() if row else []
                result = dict(zip(columns, row))
                if result.get("step_data"):
                    try:
                        result["step_data"] = json.loads(result["step_data"])
                    except Exception:
                        result["step_data"] = {}
                return result
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to load checkpoint %s: %s", job_id, e)
            return {}

    def resume(self, job_id: str) -> tuple:
        """Return (step_to_resume_from, data) for a job."""
        cp = self.load(job_id)
        if not cp:
            return ("uploaded", {})
        current_step = cp.get("step", "uploaded")
        step_data = cp.get("step_data", {})
        try:
            idx = _STEPS.index(current_step)
            if idx + 1 < len(_STEPS):
                return (_STEPS[idx + 1], step_data)
            return ("completed", step_data)
        except ValueError:
            return ("uploaded", step_data)

    def list_all(self) -> list:
        """List all checkpoints."""
        try:
            db = SessionLocal()
            try:
                rows = db.execute(
                    text("SELECT job_id, doc_id, filename, step, status, error, created_at, updated_at "
                         "FROM job_checkpoints ORDER BY updated_at DESC")
                ).fetchall()
                columns = ["job_id", "doc_id", "filename", "step", "status", "error", "created_at", "updated_at"]
                return [dict(zip(columns, row)) for row in rows]
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to list checkpoints: %s", e)
            return []

    def list_stuck_jobs(self, timeout_minutes: int = 30) -> list:
        """Find jobs that haven't updated in N minutes (likely crashed)."""
        try:
            db = SessionLocal()
            try:
                from datetime import timedelta
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
                rows = db.execute(
                    text("SELECT job_id, doc_id, filename, step, status, error, created_at, updated_at "
                         "FROM job_checkpoints WHERE status='running' AND updated_at < :cut "
                         "ORDER BY updated_at ASC"),
                    {"cut": cutoff}
                ).fetchall()
                columns = ["job_id", "doc_id", "filename", "step", "status", "error", "created_at", "updated_at"]
                return [dict(zip(columns, row)) for row in rows]
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to list stuck jobs: %s", e)
            return []

    def reset_for_retry(self, job_id: str) -> bool:
        """Reset a failed checkpoint to 'running' for retry."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            db = SessionLocal()
            try:
                result = db.execute(
                    text("UPDATE job_checkpoints SET status='running', error='', updated_at=:ua WHERE job_id=:jd AND status='failed'"),
                    {"ua": now, "jd": job_id}
                )
                db.commit()
                return result.rowcount > 0
            finally:
                db.close()
        except Exception as e:
            logger.warning("Failed to reset checkpoint for retry: %s", e)
            return False


# Singleton
checkpoint_manager = CheckpointManager()
