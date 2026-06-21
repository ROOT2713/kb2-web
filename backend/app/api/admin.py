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


# ═══════════════════════════════════════════════════════
# P1-2: Stale Detection endpoints
# ═══════════════════════════════════════════════════════

from app.services.stale_detection import (
    detect_stale_documents,
    restore_stale_document,
    get_stale_summary,
)


@router.get("/stale/summary")
def stale_summary(db: Session = Depends(get_db)):
    """获取 stale 文档统计摘要。"""
    return get_stale_summary(db)


@router.post("/stale/detect")
def run_stale_detection(
    max_days: int = Query(90, ge=7, le=365, description="超过此天数视为 stale"),
    dry_run: bool = Query(False, description="仅检测不修改"),
    db: Session = Depends(get_db),
):
    """执行 stale 检测。

    扫描所有活跃文档，将超过 max_days 未确认的标记为 stale。
    建议通过 cron 定期调用。
    """
    result = detect_stale_documents(db, max_days=max_days, dry_run=dry_run)
    return result


@router.post("/stale/restore")
def restore_stale(
    doc_id: str = Query(..., description="要恢复的文档 ID"),
    db: Session = Depends(get_db),
):
    """恢复 stale 文档为 active。

    人工确认文档仍有效后调用。
    """
    success = restore_stale_document(db, doc_id)
    if not success:
        raise HTTPException(400, "Document not found or not stale")
    return {"ok": True, "doc_id": doc_id, "status": "active"}


# ═══════════════════════════════════════════════════════
# P1-3: Quality Gates endpoints
# ═══════════════════════════════════════════════════════

from app.services.quality_gates import check_document, check_all_documents


@router.post("/quality/check")
def quality_check_single(
    doc_id: str = Query(..., description="文档 ID"),
    gates: str = Query("G1,G2,G3", description="门禁级别"),
    db: Session = Depends(get_db),
):
    """对单个文档执行质量门禁检查。"""
    result = check_document(db, doc_id, gates)
    if "error" in result:
        raise HTTPException(404, result["error"])
    db.commit()
    return result


@router.post("/quality/check-all")
def quality_check_all(
    gates: str = Query("G1,G2", description="门禁级别"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """批量检查所有活跃文档。"""
    result = check_all_documents(db, gates, limit)
    db.commit()
    return result


@router.get("/quality/stats")
def quality_stats(db: Session = Depends(get_db)):
    """获取质量门禁统计。"""
    from app.models.concept import QualityGateLog
    import json

    # 最近一次批量检查
    recent_logs = db.query(QualityGateLog).order_by(
        QualityGateLog.checked_at.desc()
    ).limit(1000).all()

    gate_stats = {}
    for log in recent_logs:
        key = log.gate_level
        if key not in gate_stats:
            gate_stats[key] = {"total": 0, "passed": 0, "failed": 0}
        gate_stats[key]["total"] += 1
        if log.passed:
            gate_stats[key]["passed"] += 1
        else:
            gate_stats[key]["failed"] += 1

    return {
        "gate_stats": gate_stats,
        "total_checks": len(recent_logs),
    }
