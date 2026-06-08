"""Query endpoint — search + LLM answer generation."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    bank: str = "general"
    top_k: int = 20


class QueryResponse(BaseModel):
    answer: str
    sources: list
    cached: bool = False


@router.post("", response_model=QueryResponse)
async def query_knowledge_base(req: QueryRequest):
    """
    Query pipeline: L1 cache → L2 semantic cache → BM25 + Dense → RRF →
    Rerank → LLM generation → cache write → return.
    """
    # TODO: Port from kb-web server.py query() (L3043-L3692)
    raise HTTPException(501, "Not implemented — pending Phase 2 migration")
