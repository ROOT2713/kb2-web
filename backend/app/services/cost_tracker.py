"""LLM cost tracker — record token usage and compute costs.

Uses kb.db (same SQLite) with a separate cost_log table.
Prices are configured for common Chinese LLM models.
"""

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Model pricing (¥ / 1M tokens) ──
# Defaults for DeepSeek V4 Pro
MODEL_PRICES: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-v4-pro": {"input": 0.14, "output": 0.28},
    "deepseek-v4-flash": {"input": 0.07, "output": 0.14},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "default": {"input": 2.00, "output": 8.00},
}

_local = threading.local()

# ── DB helpers ──

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "kb.db"


def _get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get thread-local SQLite connection."""
    key = str(db_path or DEFAULT_DB_PATH)
    if not hasattr(_local, "conn") or _local.conn_key != key:
        path = str(db_path or DEFAULT_DB_PATH)
        _local.conn = sqlite3.connect(path, check_same_thread=False)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.row_factory = sqlite3.Row
        _local.conn_key = key
        _init_table(_local.conn)
    return _local.conn


def _init_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            model TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            cost_yuan REAL NOT NULL DEFAULT 0.0,
            prompt TEXT DEFAULT '',
            response_preview TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(ts)
    """)
    conn.commit()


def get_model_price(model: str) -> dict[str, float]:
    """Get (input_price, output_price) in ¥/1M tokens for a model."""
    return MODEL_PRICES.get(model, MODEL_PRICES["default"])


# ── Public API ──


def record_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    source: str = "",
    prompt: str = "",
    response_preview: str = "",
    db_path: Optional[Path] = None,
) -> dict:
    """Record an LLM API call and return the cost record."""
    prices = get_model_price(model)
    input_cost = prompt_tokens * prices["input"] / 1_000_000
    output_cost = completion_tokens * prices["output"] / 1_000_000
    total_cost = round(input_cost + output_cost, 6)

    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db(db_path)

    # Retry on SQLITE_BUSY (multi-worker write contention)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn.execute(
                """INSERT INTO cost_log
                   (ts, model, source, prompt_tokens, completion_tokens, total_tokens, cost_yuan, prompt, response_preview)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, model, source, prompt_tokens, completion_tokens,
                 prompt_tokens + completion_tokens, total_cost,
                 prompt[:500], response_preview[:200]),
            )
            conn.commit()
            break
        except sqlite3.OperationalError as e:
            if attempt < max_retries - 1 and "busy" in str(e).lower():
                logger.warning("Cost log write busy, retrying %d/%d", attempt + 1, max_retries)
                time.sleep(0.1)
            else:
                logger.error("Cost log write failed after %d attempts: %s", attempt + 1, e)
                raise

    record = {
        "ts": now,
        "model": model,
        "source": source,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_yuan": total_cost,
    }
    return record


def get_stats(
    period: str = "today",
    db_path: Optional[Path] = None,
) -> dict:
    """Get cost statistics for a period. period: today, week, month, all."""
    conn = _get_db(db_path)
    now = datetime.now(timezone.utc)

    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        cutoff = now - timedelta(days=7)
    elif period == "month":
        cutoff = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)

    row = conn.execute(
        """SELECT
            COUNT(*) as call_count,
            COALESCE(SUM(prompt_tokens), 0) as total_prompt,
            COALESCE(SUM(completion_tokens), 0) as total_completion,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(cost_yuan), 0) as total_cost
           FROM cost_log WHERE ts >= ?""",
        (cutoff.isoformat(),),
    ).fetchone()

    # Breakdown by model
    models = conn.execute(
        """SELECT model, COUNT(*) as calls,
                  COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                  COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                  COALESCE(SUM(cost_yuan), 0) as cost_yuan
           FROM cost_log WHERE ts >= ?
           GROUP BY model ORDER BY cost_yuan DESC""",
        (cutoff.isoformat(),),
    ).fetchall()

    return {
        "period": period,
        "call_count": row["call_count"],
        "total_prompt_tokens": row["total_prompt"],
        "total_completion_tokens": row["total_completion"],
        "total_tokens": row["total_tokens"],
        "total_cost_yuan": round(row["total_cost"], 4),
        "by_model": [dict(m) for m in models],
    }
