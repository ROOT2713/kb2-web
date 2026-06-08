"""Synonym management endpoints — CRUD for query synonym expansion.

Ported from: kb-web server.py list_synonyms/add_synonym/update_synonym/
             delete_synonym/_refresh_synonym_cache L4958-L5022
"""

import logging
import time as _time

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.synonym import Synonym
from app.services.retrieval import _synonym_cache
from app.middleware.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Synonym cache TTL (seconds) ──────────────────────────────────
_SYNONYM_TTL = 300  # 5 min


def _refresh_synonym_cache(db: Session):
    """Refresh in-memory synonym cache (matches v1 _refresh_synonym_cache L5011-L5019)."""
    try:
        rows = db.execute(
            sa_text("SELECT term, expansion FROM synonym_map")
        ).fetchall()
        _synonym_cache["rows"] = rows
        _synonym_cache["ts"] = _time.time()
        logger.info("Synonym cache refreshed: %d entries", len(rows))
    except Exception as e:
        logger.warning("Failed to refresh synonym cache: %s", e)


# ═══════════════════════════════════════════════════════════════════
# Route: GET / — list all synonyms
# ═══════════════════════════════════════════════════════════════════

@router.get("")
async def list_synonyms(db: Session = Depends(get_db)):
    """List all synonym mappings (v1 L4958-L4965)."""
    rows = db.execute(
        sa_text("SELECT id, term, expansion, category FROM synonym_map ORDER BY category, term")
    ).fetchall()
    return [{"id": r[0], "term": r[1], "expansion": r[2], "category": r[3] or ""} for r in rows]


# ═══════════════════════════════════════════════════════════════════
# Route: POST / — add a synonym
# ═══════════════════════════════════════════════════════════════════

@router.post("")
async def add_synonym(
    term: str = Form(...),
    expansion: str = Form(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
):
    """Add a synonym mapping (v1 L4968-L4978)."""
    db.execute(
        sa_text("INSERT INTO synonym_map (term, expansion, category) VALUES (:term, :expansion, :category)"),
        {"term": term.strip(), "expansion": expansion.strip(), "category": category.strip()}
    )
    db.commit()
    _refresh_synonym_cache(db)
    return {"ok": True, "message": f"Added: {term} -> {expansion}"}


# ═══════════════════════════════════════════════════════════════════
# Route: PUT /{syn_id} — update a synonym
# ═══════════════════════════════════════════════════════════════════

@router.put("/{syn_id}")
async def update_synonym(
    syn_id: int,
    term: str = Form(...),
    expansion: str = Form(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
):
    """Update a synonym mapping (v1 L4981-L4993)."""
    result = db.execute(
        sa_text("UPDATE synonym_map SET term=:term, expansion=:expansion, category=:category WHERE id=:id"),
        {"term": term.strip(), "expansion": expansion.strip(), "category": category.strip(), "id": syn_id}
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Synonym not found")
    _refresh_synonym_cache(db)
    return {"ok": True, "message": f"Updated: {term} -> {expansion}"}


# ═══════════════════════════════════════════════════════════════════
# Route: DELETE /{syn_id} — delete a synonym
# ═══════════════════════════════════════════════════════════════════

@router.delete("/{syn_id}")
async def delete_synonym(
    syn_id: int,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete a synonym mapping (v1 L4996-L5008)."""
    result = db.execute(
        sa_text("DELETE FROM synonym_map WHERE id=:id"),
        {"id": syn_id}
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Synonym not found")
    _refresh_synonym_cache(db)
    return {"ok": True, "message": "Deleted"}
