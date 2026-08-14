"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

# ── 日志配置：确保所有子模块的 logger.info() 输出到 journalctl ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,  # 覆盖 uvicorn 的默认 logger 配置
)
# 将 uvicorn 自带的 acess/error logger 保持原有格式
for _uv_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    _uv_l = logging.getLogger(_uv_name)
    if not _uv_l.handlers:
        _uv_l.setLevel(logging.INFO)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from app.config import settings
from app.api.router import api_router
from app.middleware.jwt_auth import get_current_user
from app.middleware.error_handler import global_exception_handler
from app.middleware.request_id import RequestIDMiddleware

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup / shutdown hooks."""
    # ── startup ──
    from app.models.database import init_db
    init_db()

    from app.middleware.request_id import _ensure_rid_filter
    _ensure_rid_filter()

    from app.services.cache_service import warmup_bm25 as warmup_caches
    await warmup_caches()

    yield

    # ── shutdown ──


app = FastAPI(
    title="kb-web",
    version="2.0.0",
    description="知识库 Web 服务 — Hindsight + LLM 驱动的智能文档检索与问答",
    lifespan=lifespan,
    redirect_slashes=False,  # 禁止尾斜杠重定向，避免 catch-all 拦截 API POST
    docs_url=None,           # 生产关闭 Swagger/OpenAPI 暴露（2026-08-13 安全加固）
    redoc_url=None,
    openapi_url=None,
)

app.add_exception_handler(Exception, global_exception_handler)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request-ID (最外层中间件，覆盖全链路) ──
app.add_middleware(RequestIDMiddleware)

# ── HTTP 安全头中间件（2026-08-13 CC 审查 P2：防点击劫持/MIME嗅探）──
class SecurityHeadersMiddleware:
    """注入基础安全响应头：X-Frame-Options / X-Content-Type-Options / Referrer-Policy / CSP"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                extra = [
                    (b"X-Frame-Options", b"DENY"),
                    (b"X-Content-Type-Options", b"nosniff"),
                    (b"Referrer-Policy", b"no-referrer"),
                    (b"Content-Security-Policy", b"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"),
                ]
                message["headers"] = list(headers) + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

# ── Auth routes (NO JWT required) ──
from app.api.auth import router as auth_router  # noqa: E402
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])

# ── Protected API routes (JWT required) ──
app.include_router(api_router, prefix="/api")


# ── V1 compatibility aliases ──
@app.get("/api/fetch-standard", include_in_schema=False)
async def v1_compat_fetch_standard(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/documents/fetch-standard", status_code=307)

@app.post("/api/fetch-standard", include_in_schema=False)
async def v1_compat_fetch_standard_post(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/documents/fetch-standard", status_code=307)

@app.get("/api/web-search", include_in_schema=False)
async def v1_compat_web_search(user: str = Depends(get_current_user)):
    raise HTTPException(
        status_code=405,
        detail="/api/web-search requires POST form fields: q, bank, context. Use POST /api/query/web-search or POST /api/web-search.",
    )

@app.post("/api/web-search", include_in_schema=False)
async def v1_compat_web_search_post(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/query/web-search", status_code=307)

@app.get("/api/categories", include_in_schema=False)
async def v1_compat_categories(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/banks/categories", status_code=307)

@app.get("/api/wiki", include_in_schema=False)
async def v1_compat_wiki(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/banks/wiki", status_code=307)

@app.get("/api/stats", include_in_schema=False)
async def v1_compat_stats(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/admin/stats", status_code=307)

@app.get("/api/rag-eval", include_in_schema=False)
async def v1_compat_rag_eval(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/documents/rag-eval", status_code=307)

@app.get("/api/audit", include_in_schema=False)
async def v1_compat_audit(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/documents/audit", status_code=307)

@app.post("/api/audit/refetch", include_in_schema=False)
async def v1_compat_refetch(user: str = Depends(get_current_user)):
    return RedirectResponse(url="/api/documents/refetch", status_code=307)


# ── Health check (no auth) ──
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# ── Frontend SPA (static files + fallback) ──
if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve frontend SPA — return index.html for all non-API routes."""
        # ── Skip API routes — let them fall through to proper handlers ──
        if full_path.startswith("api/"):
            from fastapi import HTTPException as _HE
            raise _HE(status_code=404)
        # ── 2026-08-14 安全加固：OpenAPI/Swagger 显式 404，防 catch-all 吞掉返回 200 ──
        if full_path in ("openapi.json", "docs", "redoc"):
            raise HTTPException(status_code=404)
        # ── Path traversal protection (C1 fix) ──
        if ".." in full_path.split("/"):
            raise HTTPException(status_code=404)
        file_path = (FRONTEND_DIR / full_path).resolve()
        if not str(file_path).startswith(str(FRONTEND_DIR.resolve())):
            raise HTTPException(status_code=404)
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
