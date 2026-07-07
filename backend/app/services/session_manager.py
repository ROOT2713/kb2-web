"""Session manager — multi-turn domain locking via document ID whitelist.

Thread-safe in-memory store with TTL-based expiration.
Used by query() to maintain per-session document scope across turns.
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)

_SESSION_STORE: dict = {}  # session_id → {"doc_ids": set, "bank": str, "updated_at": float}
_SESSION_TTL = 600  # 10 minutes
_LOCK = threading.Lock()
_LAST_CLEANUP: float = 0
_CLEANUP_INTERVAL = 60  # lazy cleanup every 60s


def get_session(session_id: str) -> dict | None:
    """Retrieve session state.

    Returns dict with "doc_ids" (set), "bank" (str), "updated_at" (float),
    or None if session not found or expired.
    """
    _lazy_cleanup()
    with _LOCK:
        entry = _SESSION_STORE.get(session_id)
        if entry is None:
            return None
        if time.time() - entry["updated_at"] > _SESSION_TTL:
            del _SESSION_STORE[session_id]
            logger.info("[SESSION] Expired session %s (TTL=%ds)", session_id[:8], _SESSION_TTL)
            return None
        return {
            "doc_ids": entry["doc_ids"],
            "bank": entry["bank"],
            "updated_at": entry["updated_at"],
        }


def create_or_update_session(session_id: str, doc_ids: set, bank: str) -> dict:
    """Create or update a session with the given document IDs and bank.

    Args:
        session_id: Unique session identifier.
        doc_ids: Set of document IDs to lock to.
        bank: Current bank context.

    Returns:
        The updated session dict.
    """
    with _LOCK:
        now = time.time()
        _SESSION_STORE[session_id] = {
            "doc_ids": set(doc_ids),
            "bank": bank,
            "updated_at": now,
        }
        logger.info(
            "[SESSION] %s session %s with %d doc_ids, bank=%s",
            "Created" if len(_SESSION_STORE) <= 1 else "Updated",
            session_id[:8], len(doc_ids), bank,
        )
        return {
            "doc_ids": _SESSION_STORE[session_id]["doc_ids"],
            "bank": _SESSION_STORE[session_id]["bank"],
            "updated_at": _SESSION_STORE[session_id]["updated_at"],
        }


def release_session(session_id: str) -> bool:
    """Remove a session from the store.

    Returns True if session existed and was removed.
    """
    with _LOCK:
        if session_id in _SESSION_STORE:
            del _SESSION_STORE[session_id]
            logger.info("[SESSION] Released session %s", session_id[:8])
            return True
        return False


def _lazy_cleanup():
    """Periodic cleanup of expired sessions. Called on every session read."""
    global _LAST_CLEANUP
    now = time.time()
    if now - _LAST_CLEANUP < _CLEANUP_INTERVAL:
        return
    _LAST_CLEANUP = now
    with _LOCK:
        expired = [
            sid for sid, entry in _SESSION_STORE.items()
            if now - entry["updated_at"] > _SESSION_TTL
        ]
        for sid in expired:
            del _SESSION_STORE[sid]
        if expired:
            logger.info("[SESSION] Lazy cleanup removed %d expired sessions", len(expired))
