"""Query logger — logs every query to SQLite for monitoring and analysis.

Fire-and-forget pattern: all writes are async/non-blocking.
Adds <5ms overhead to the query path.
"""

import json
import logging
import time
from datetime import datetime, timezone

from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────
_MAX_RECENT_QUERIES = 5000  # Trim table when exceeding this


# ── Public API ─────────────────────────────────────────────────────────


def log_query(query_text: str, bank: str, answer_length: int,
              source_count: int, rejected: bool, rejection_reason: str = "",
              latency_ms: int = 0, cache_hit: bool = False,
              concept_used: bool = False) -> None:
    """Log a query to the query_log table. Fire-and-forget — never raises."""
    try:
        db = SessionLocal()
        try:
            db.execute(
                "INSERT INTO query_log "
                "(query_text, bank, timestamp, answer_length, source_count, "
                " rejected, rejection_reason, latency_ms, cache_hit, concept_used) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (query_text[:500], bank, datetime.now(timezone.utc).isoformat(),
                 answer_length, source_count,
                 1 if rejected else 0, rejection_reason[:200],
                 latency_ms, 1 if cache_hit else 0, 1 if concept_used else 0)
            )
            db.commit()

            # Trim old entries
            count = db.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
            if count > _MAX_RECENT_QUERIES:
                db.execute(
                    "DELETE FROM query_log WHERE id IN "
                    "(SELECT id FROM query_log ORDER BY id ASC LIMIT ?)",
                    (count - _MAX_RECENT_QUERIES,)
                )
                db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Query logger failed (non-fatal): %s", e)


def get_recent_queries(limit: int = 100, rejected: bool = None,
                       bank: str = None, since: str = None) -> list:
    """Get recent query log entries."""
    try:
        db = SessionLocal()
        try:
            sql = "SELECT * FROM query_log WHERE 1=1"
            params = []
            if rejected is not None:
                sql += " AND rejected = ?"
                params.append(1 if rejected else 0)
            if bank:
                sql += " AND bank = ?"
                params.append(bank)
            if since:
                sql += " AND timestamp >= ?"
                params.append(since)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = db.execute(sql, params).fetchall()
            columns = [desc[0] for desc in db.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to get query log: %s", e)
        return []


def get_query_stats() -> dict:
    """Get today's query statistics."""
    try:
        db = SessionLocal()
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            total = db.execute(
                "SELECT COUNT(*) FROM query_log WHERE timestamp >= ?",
                (today,)
            ).fetchone()[0]
            rejected = db.execute(
                "SELECT COUNT(*) FROM query_log WHERE rejected = 1 AND timestamp >= ?",
                (today,)
            ).fetchone()[0]
            avg_latency = db.execute(
                "SELECT COALESCE(AVG(latency_ms), 0) FROM query_log WHERE timestamp >= ?",
                (today,)
            ).fetchone()[0]
            # Rejection reasons breakdown
            reasons = db.execute(
                "SELECT rejection_reason, COUNT(*) as cnt FROM query_log "
                "WHERE rejected = 1 AND timestamp >= ? AND rejection_reason != '' "
                "GROUP BY rejection_reason ORDER BY cnt DESC LIMIT 10",
                (today,)
            ).fetchall()
            return {
                "total_today": total,
                "rejected_today": rejected,
                "rejection_rate": round(rejected / total * 100, 1) if total > 0 else 0,
                "avg_latency_ms": round(avg_latency, 0),
                "top_rejection_reasons": [
                    {"reason": r[0], "count": r[1]} for r in reasons
                ],
            }
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to get query stats: %s", e)
        return {"error": str(e)}
