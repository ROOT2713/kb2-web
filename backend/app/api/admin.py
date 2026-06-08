"""Admin endpoints — stats, cache management, health.

Ported from: kb-web server.py stats() L4253-L4275,
             health() L2601-L2629 (already in main.py)
             _get_active_hindsight_banks() L1803-L1823 (re-export from retrieval)
             get_bank_config() L1824-L1829 (re-export from retrieval)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db
from app.services.retrieval import _get_active_hindsight_banks, _hindsight_request, get_bank_config
from app.services.cache_service import invalidate_bm25_cache
from app.middleware.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Route: GET /stats — system statistics
# ═══════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats():
    """Knowledge base statistics (v1 L4253-L4275)."""
    active_banks = await _get_active_hindsight_banks()
    total_nodes = 0
    total_documents = 0
    total_links = 0
    for bank_id in active_banks:
        try:
            result = await _hindsight_request(f"/v1/default/banks/{bank_id}/stats", timeout=10)
            total_nodes += result.get("total_nodes", 0)
            total_documents += result.get("total_documents", 0)
            total_links += result.get("total_links", 0)
        except Exception as e:
            logger.warning("Stats: bank %s failed: %s", bank_id, e)
    return {
        "total_nodes": total_nodes,
        "total_documents": total_documents,
        "total_links": total_links,
    }


# ═══════════════════════════════════════════════════════════════════
# Route: POST /cache/invalidate — invalidate caches
# ═══════════════════════════════════════════════════════════════════

@router.post("/cache/invalidate")
async def admin_invalidate_cache(
    bank: str = Query("all"),
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Invalidate BM25 + query cache for a bank (admin-only)."""
    invalidate_bm25_cache(bank=bank if bank != "all" else None)

    # Also invalidate query cache
    try:
        if bank == "all":
            db.execute(sa_text("DELETE FROM query_cache"))
        else:
            db.execute(sa_text("DELETE FROM query_cache WHERE bank=:bank"), {"bank": bank})
        db.commit()
    except Exception as e:
        raise HTTPException(500, f"Cache invalidation failed: {e}")

    return {"ok": True, "bank": bank}


# ═══════════════════════════════════════════════════════════════════
# Route: GET /banks/active — list active Hindsight banks
# ═══════════════════════════════════════════════════════════════════

@router.get("/banks/active")
async def list_active_banks():
    """List currently active Hindsight banks."""
    active = await _get_active_hindsight_banks()
    return {"active_banks": active}


# ═══════════════════════════════════════════════════════════════════
# Route: GET /banks/config — show bank configs
# ═══════════════════════════════════════════════════════════════════

@router.get("/banks/config")
async def show_bank_configs():
    """Show all bank configurations (sensitive prompts redacted)."""
    from app.services.retrieval import BANKS
    result = {}
    for key, cfg in BANKS.items():
        result[key] = {
            "name": cfg.get("name", ""),
            "hindsight": cfg.get("hindsight"),
            "description": cfg.get("description", ""),
            "prompt_preview": (cfg.get("prompt", "") or "")[:60] + "...",
        }
    return {"banks": result}


# ═══════════════════════════════════════════════════════════════════
# Route: GET /health — detailed health check (import from main.py)
# ═══════════════════════════════════════════════════════════════════
# Note: basic health check is already in main.py at /health.
# This provides a more detailed version under /api/admin/health.

@router.get("/health")
async def admin_health():
    """Detailed health check including Hindsight connectivity."""
    health_status = {
        "status": "ok",
        "version": "2.0.0",
        "hindsight": "unknown",
        "db": "unknown",
    }
    # DB check
    try:
        db = next(get_db())
        db.execute(sa_text("SELECT 1"))
        db.close()
        health_status["db"] = "ok"
    except Exception as e:
        health_status["db"] = f"error: {e}"
        health_status["status"] = "degraded"

    # Hindsight check
    try:
        result = await _hindsight_request("/health", timeout=5)
        health_status["hindsight"] = "ok" if result.get("status") == "ok" else "degraded"
    except Exception:
        health_status["hindsight"] = "unreachable"
        health_status["status"] = "degraded"

    return health_status
