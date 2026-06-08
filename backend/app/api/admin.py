"""Admin endpoints — audit, benchmark, cache management."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/audit")
async def audit_knowledge_base():
    """Audit knowledge base: coverage, orphan detection, quality scoring."""
    raise HTTPException(501, "Not implemented")


@router.post("/cache/invalidate")
async def invalidate_cache(bank: str = "all"):
    """Invalidate query cache for a bank."""
    raise HTTPException(501, "Not implemented")


@router.get("/stats")
async def get_stats():
    """System stats: doc count, chunk count, cache hit rate, etc."""
    raise HTTPException(501, "Not implemented")
