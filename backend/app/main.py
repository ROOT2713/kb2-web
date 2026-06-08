"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup / shutdown hooks."""
    # ── startup ──
    from app.models.database import init_db
    init_db()

    from app.services.cache_service import warmup_bm25 as warmup_caches
    await warmup_caches()

    yield

    # ── shutdown ──


app = FastAPI(
    title="kb-web",
    version="2.0.0",
    description="知识库 Web 服务 — Hindsight + LLM 驱动的智能文档检索与问答",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ──
app.include_router(api_router, prefix="/api")


# ── Health check ──
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}
