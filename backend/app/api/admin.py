"""Admin endpoints — stats, cache management, health.

Ported from: kb-web server.py stats() L4253-L4275,
             health() L2601-L2629 (already in main.py)
             _get_active_hindsight_banks() L1803-L1823 (re-export from retrieval)
             get_bank_config() L1824-L1829 (re-export from retrieval)
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db
from app.models.audit import AuditLog
from app.repositories.vector_repo import get_vector_store
from app.services.retrieval import _get_active_hindsight_banks, _hindsight_request, get_bank_config
from app.services.cache_service import invalidate_bm25_cache
from app.services.cost_tracker import get_stats as get_cost_stats

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Route: GET /stats — system statistics
# ═══════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats():
    """Knowledge base statistics (v1 L4253-L4275)."""
    if settings.vector_backend == "pgvector":
        store = get_vector_store()
        active_banks = await _get_active_hindsight_banks()
        total_nodes = 0
        total_documents = 0
        for bank_id in active_banks:
            try:
                count = await store.get_document_chunk_count(bank_id)
                total_nodes += count
                total_documents += 1  # bank has at least some chunks
            except Exception as e:
                logger.warning("Stats: bank %s failed: %s", bank_id, e)
        return {
            "total_nodes": total_nodes,
            "total_documents": total_documents,
            "total_links": 0,
        }
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
    """Detailed health check including vector store connectivity."""
    health_status = {
        "status": "ok",
        "version": "2.0.0",
        "vector_store": "unknown",
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

    # Vector store check
    try:
        if settings.vector_backend == "pgvector":
            store = get_vector_store()
            health_status["vector_store"] = "ok" if await store.health() else "degraded"
        else:
            result = await _hindsight_request("/health", timeout=5)
            health_status["vector_store"] = "ok" if result.get("status") == "ok" else "degraded"
    except Exception:
        health_status["vector_store"] = "unreachable"
        health_status["status"] = "degraded"

    # MinerU 解析器健康
    try:
        ms = get_mineru_stats()
        health_status["mineru"] = ms
        if ms["fail"] > 5 and ms["success"] == 0:
            health_status["status"] = "degraded"
    except Exception:
        health_status["mineru"] = "unavailable"

    return health_status


# ═══════════════════════════════════════════════════════
# P1-3: Quality Gates endpoints
# ═══════════════════════════════════════════════════════

from app.services.parsing import get_mineru_stats
from app.services.quality_gates import check_document, check_all_documents

# 【FIX-R2-13】原 L182+L185 双相同 @router.post("/quality/check") 堆叠——
# 第一个空装饰器把同一路由注册两次（Starlette 匹配首个），冗余技术债。删空装饰器。
# 【FIX-R3-10】单文档端点 /quality/check 下线（前端/测试 0 调用，与 check-all/stats 冗余）。
# check_document 保留——check-all 内部仍使用；外部逐文档检查走 check-all + 前端过滤。

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


# ═══════════════════════════════════════════════════════
# P2-1: Confidence endpoints
# ═══════════════════════════════════════════════════════

from app.services.confidence import (
    compute_document_confidence,
    update_concept_confidence,
    update_all_confidences,
    get_confidence_summary,
)


@router.get("/confidence/summary")
def confidence_summary(db: Session = Depends(get_db)):
    """获取 confidence 统计摘要。"""
    return get_confidence_summary(db)


@router.post("/confidence/recalc")
def recalculate_confidences(
    db: Session = Depends(get_db),
):
    """批量重算所有 concept 的 confidence。"""
    result = update_all_confidences(db)
    db.commit()
    return result


@router.get("/confidence/{doc_id}")
def doc_confidence(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """获取单个文档的 confidence。"""
    conf = compute_document_confidence(db, doc_id)
    return {"doc_id": doc_id, "confidence": conf}


# ═══════════════════════════════════════════════════════
# P2-2: Concept Summary endpoints
# ═══════════════════════════════════════════════════════

from app.services.concept_summary import (
    generate_summaries_batch,
    generate_all_summaries,
)


@router.post("/summaries/generate")
async def generate_doc_summaries(
    doc_id: str = Query(..., description="文档 ID"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """为单个文档的 concept 生成摘要。"""
    count = await generate_summaries_batch(db, doc_id, limit)
    db.commit()
    return {"doc_id": doc_id, "generated": count}


@router.post("/summaries/generate-all")
async def generate_all_concept_summaries(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """批量为所有无摘要的 concept 生成摘要。"""
    result = await generate_all_summaries(db, limit)
    db.commit()
    return result


# ═══════════════════════════════════════════════════════
# P1: Lifecycle endpoints — document lifecycle management
# ═══════════════════════════════════════════════════════

from app.services.stale_detection import (
    detect_stale_documents,
    restore_stale_document,
    get_stale_summary,
)


@router.post("/lifecycle/confirm/{doc_id}")
def lifecycle_confirm(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """用户确认文档知识仍有效。

    更新以下字段:
    - last_confirmed = 当前时间
    - review_required = 0
    - stale_at = None (清除过期标记)
    - stale_reason = None

    如果文档当前是 stale 状态，同时恢复为 active。
    """
    from app.models.document import Document
    from datetime import datetime, timezone

    doc = db.query(Document).filter(Document.doc_id == doc_id).first()
    if not doc:
        raise HTTPException(404, f"文档不存在: {doc_id}")

    now = datetime.now(timezone.utc)
    doc.last_confirmed = now
    doc.review_required = 0
    doc.stale_at = None
    doc.stale_reason = None

    # 如果当前是 stale，恢复为 active
    if doc.status == "stale":
        doc.status = "active"
        doc.verified_at = now

    db.commit()

    logger.info("Lifecycle confirm: doc=%s status=%s", doc_id[:8], doc.status)
    return {
        "ok": True,
        "doc_id": doc_id,
        "status": doc.status,
        "last_confirmed": now.isoformat(),
    }


@router.get("/stale/detect")
def stale_detect(
    max_days: int = Query(90, ge=1, le=365),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    """检测过期文档（管理员，可指定 max_days）。"""
    result = detect_stale_documents(db, max_days=max_days, dry_run=dry_run)
    db.commit()
    return result


@router.get("/stale/summary")
def stale_summary(
    db: Session = Depends(get_db),
):
    """获取 stale 文档统计摘要（管理员）。"""
    return get_stale_summary(db)


@router.post("/stale/restore/{doc_id}")
def stale_restore(
    doc_id: str,
    db: Session = Depends(get_db),
):
    """恢复 stale 文档为 active（管理员）。"""
    ok = restore_stale_document(db, doc_id)
    if not ok:
        raise HTTPException(404, f"文档不存在或不是 stale 状态: {doc_id}")
    return {"ok": True, "doc_id": doc_id}


# ═══════════════════════════════════════════════════════
# Route: GET /costs — LLM cost monitoring
# ═══════════════════════════════════════════════════════


@router.get("/costs")
async def admin_cost_stats(
    period: str = Query("today", regex="^(today|week|month|all)$"),
):
    """Get LLM cost statistics (admin-only)."""
    return get_cost_stats(period=period)


# ═══════════════════════════════════════════════════════
# Quality Gates — document quality checks
# ═══════════════════════════════════════════════════════

from app.services.quality_gates import (
    check_document as qg_check_document,
    check_all_documents as qg_check_all,
    get_quality_gates_summary,
)


@router.get("/quality-gates/check/{doc_id}")
async def quality_gates_check_single(
    doc_id: str,
    gates: str = Query("G1,G2,G3", description="门禁级别"),
    db: Session = Depends(get_db),
):
    """检查单个文档的质量门禁。"""
    result = qg_check_document(db, doc_id, gates=gates)
    return result


@router.post("/quality-gates/check/all")
async def quality_gates_check_all(
    gates: str = Query("G1,G2", description="门禁级别"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """批量检查所有活跃文档的质量门禁。"""
    result = qg_check_all(db, gates=gates, limit=limit)
    return result


@router.get("/quality-gates/summary")
async def quality_gates_summary_endpoint(
    db: Session = Depends(get_db),
):
    """获取质量门禁统计摘要。"""
    return get_quality_gates_summary(db)


@router.get("/audit")
async def get_audit_logs(
    user_id: str = Query(None, description="按用户筛选"),
    from_date: str = Query(None, description="起始日期 (YYYY-MM-DD)"),
    to_date: str = Query(None, description="截止日期 (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """查询审计日志（仅 admin）。"""
    query = db.query(AuditLog)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if from_date:
        try:
            dt = datetime.strptime(from_date, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= dt)
        except ValueError:
            raise HTTPException(400, "from_date 格式错误，应为 YYYY-MM-DD")
    if to_date:
        try:
            dt = datetime.strptime(to_date, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at < dt.replace(hour=23, minute=59, second=59))
        except ValueError:
            raise HTTPException(400, "to_date 格式错误，应为 YYYY-MM-DD")

    total = query.count()
    logs = query.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "query": log.query,
                "answer": log.answer[:200] if log.answer else None,
                "cache_hit": log.cache_hit,
                "rejected": log.rejected,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# Route: GET /categories — available document categories
# ═══════════════════════════════════════════════════════════════════

@router.get("/categories")
async def get_categories():
    """Return hierarchical category tree: super_category → categories → subcategories."""
    from app.services.category_rules import CATEGORIES, SUPER_CATEGORY_MAP, SUPER_CATEGORY_ORDER
    
    # Group categories by super_category
    groups = {}
    for ck, cl in CATEGORIES.items():
        sc = SUPER_CATEGORY_MAP.get(ck, "其他")
        if sc not in groups:
            groups[sc] = {"name": sc, "categories": []}
        groups[sc]["categories"].append({
            "key": ck, "label": cl, "isolated": ck in ("daily", "news"),
        })
    
    # Return in defined order
    result = []
    for sc in SUPER_CATEGORY_ORDER:
        if sc in groups:
            result.append(groups.pop(sc))
    # Any remaining
    result.extend(groups.values())
    return result


# ═══════════════════════════════════════════════════════════════════
# Route: GET /queries — recent query log
# ═══════════════════════════════════════════════════════════════════

@router.get("/queries")
async def get_queries(
    limit: int = Query(100, ge=1, le=1000),
    rejected: bool = None,
    bank: str = None,
    since: str = None,
):
    """Return recent query log entries."""
    from app.services.query_logger import get_recent_queries
    return get_recent_queries(limit=limit, rejected=rejected, bank=bank, since=since)


# ═══════════════════════════════════════════════════════════════════
# Route: GET /query-stats — query statistics
# ═══════════════════════════════════════════════════════════════════

@router.get("/query-stats")
async def get_query_stats():
    """Return today's query statistics (total, rejection rate, latency)."""
    from app.services.query_logger import get_query_stats
    return get_query_stats()


# ═══════════════════════════════════════════════════════════════════
# Route: GET /checkpoints — list all checkpoints
# ═══════════════════════════════════════════════════════════════════

@router.get("/checkpoints")
async def list_checkpoints():
    """Return all ingestion checkpoints."""
    from app.services.job_checkpoint import checkpoint_manager
    return {"checkpoints": checkpoint_manager.list_all()}


# ═══════════════════════════════════════════════════════════════════
# Route: GET /checkpoints/stuck — list stuck jobs
# ═══════════════════════════════════════════════════════════════════

@router.get("/checkpoints/stuck")
async def list_stuck_checkpoints(timeout: int = Query(30, ge=5, le=120)):
    """Return checkpoints that haven't been updated in N minutes (likely crashed)."""
    from app.services.job_checkpoint import checkpoint_manager
    return {"stuck": checkpoint_manager.list_stuck_jobs(timeout_minutes=timeout)}


# ═══════════════════════════════════════════════════════════════════
# Route: POST /checkpoints/{job_id}/retry — retry a failed checkpoint
# ═══════════════════════════════════════════════════════════════════

@router.post("/checkpoints/{job_id}/retry")
async def retry_checkpoint(job_id: str):
    """Mark a failed checkpoint as ready for retry."""
    from app.services.job_checkpoint import checkpoint_manager
    ok = checkpoint_manager.reset_for_retry(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Checkpoint {job_id} not found")
    return {"ok": True, "job_id": job_id}
