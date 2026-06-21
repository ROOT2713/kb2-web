"""Unified API router — aggregates all endpoint modules.

All routes under this router require JWT authentication via
the `get_current_user` dependency.
"""

from fastapi import APIRouter, Depends

from app.middleware.jwt_auth import get_current_user
from app.api import upload, query, documents, banks, synonyms, admin, concepts

api_router = APIRouter(dependencies=[Depends(get_current_user)])

api_router.include_router(upload.router,    prefix="/upload",    tags=["上传"])
api_router.include_router(query.router,     prefix="/query",     tags=["查询"])
api_router.include_router(documents.router, prefix="/documents", tags=["文档"])
api_router.include_router(banks.router,     prefix="/banks",     tags=["知识库"])
api_router.include_router(synonyms.router,  prefix="/synonyms",  tags=["同义词"])
api_router.include_router(admin.router,     prefix="/admin",     tags=["管理"])
api_router.include_router(concepts.router,  prefix="/concepts",  tags=["概念"])
