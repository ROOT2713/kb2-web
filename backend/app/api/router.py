"""Unified API router — aggregates all endpoint modules."""

from fastapi import APIRouter

from app.api import upload, query, documents, banks, synonyms, admin

api_router = APIRouter()

api_router.include_router(upload.router,    prefix="/upload",    tags=["上传"])
api_router.include_router(query.router,     prefix="/query",     tags=["查询"])
api_router.include_router(documents.router, prefix="/documents", tags=["文档"])
api_router.include_router(banks.router,     prefix="/banks",     tags=["知识库"])
api_router.include_router(synonyms.router,  prefix="/synonyms",  tags=["同义词"])
api_router.include_router(admin.router,     prefix="/admin",     tags=["管理"])
