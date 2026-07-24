"""Wiki API — CRUD + search + relation management for structured knowledge layer.

Endpoints:
  GET    /wiki/search       — public, search published entries
  GET    /wiki/entry/{id}   — public, view entry with relations
  GET    /wiki/categories   — public, list category tree

  POST   /wiki/entry        — admin, create entry
  PUT    /wiki/entry/{id}   — admin, update entry
  DELETE /wiki/entry/{id}   — admin, delete entry
  POST   /wiki/relation     — admin, add relation
  DELETE /wiki/relation/{id} — admin, remove relation
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.middleware.jwt_auth import get_current_user
from app.services import wiki_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Wiki"])


# ── Pydantic schemas ──


class EntryCreate(BaseModel):
    title: str
    standard_no: str = ""
    category: str = ""
    subcategory: str = ""
    tags: list = []
    summary: str = ""
    content: dict = {}
    source_doc_id: str = ""
    importance: int = 0
    status: str = "draft"


class EntryUpdate(BaseModel):
    title: Optional[str] = None
    standard_no: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: Optional[list] = None
    summary: Optional[str] = None
    content: Optional[dict] = None
    source_doc_id: Optional[str] = None
    importance: Optional[int] = None
    status: Optional[str] = None


class RelationCreate(BaseModel):
    source_entry_id: int
    target_entry_id: int
    relation_type: str
    description: str = ""


# ── Public endpoints ──


@router.get("/wiki/search")
async def wiki_search(
    q: str = Query("", description="搜索关键词"),
    category: str = Query("", description="分类过滤"),
    standard_no: str = Query("", description="标准编号过滤"),
    status: str = Query("published", description="状态过滤"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """搜索 Wiki 条目（默认只返回 published 条目）"""
    items = wiki_service.search_entries(
        query=q, category=category, standard_no=standard_no,
        status=status, limit=limit, offset=offset,
    )
    total = wiki_service.search_entries_count(
        query=q, category=category, standard_no=standard_no, status=status,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/wiki/entry/{entry_id}")
async def wiki_get_entry(entry_id: int):
    """获取 Wiki 条目详情（含交叉引用）"""
    entry = wiki_service.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "条目不存在")
    return entry


@router.get("/wiki/categories")
async def wiki_categories():
    """获取 Wiki 分类树"""
    return {"categories": wiki_service.list_categories()}


# ── Admin endpoints (require auth) ──


@router.post("/wiki/entry", dependencies=[Depends(get_current_user)])
async def wiki_create_entry(data: EntryCreate):
    """创建 Wiki 条目"""
    entry_id = wiki_service.create_entry(
        title=data.title, standard_no=data.standard_no,
        category=data.category, subcategory=data.subcategory,
        tags=data.tags, summary=data.summary, content=data.content,
        source_doc_id=data.source_doc_id, importance=data.importance,
        status=data.status,
    )
    if not entry_id:
        raise HTTPException(500, "创建失败")
    return {"id": entry_id, "message": "创建成功"}


@router.put("/wiki/entry/{entry_id}", dependencies=[Depends(get_current_user)])
async def wiki_update_entry(entry_id: int, data: EntryUpdate):
    """更新 Wiki 条目"""
    ok = wiki_service.update_entry(
        entry_id,
        **{k: v for k, v in data.model_dump().items() if v is not None},
    )
    if not ok:
        raise HTTPException(404, "条目不存在或更新失败")
    return {"message": "更新成功"}


@router.delete("/wiki/entry/{entry_id}", dependencies=[Depends(get_current_user)])
async def wiki_delete_entry(entry_id: int):
    """删除 Wiki 条目"""
    ok = wiki_service.delete_entry(entry_id)
    if not ok:
        raise HTTPException(404, "条目不存在")
    return {"message": "删除成功"}


@router.post("/wiki/relation", dependencies=[Depends(get_current_user)])
async def wiki_add_relation(data: RelationCreate):
    """添加交叉引用"""
    ok = wiki_service.add_relation(
        data.source_entry_id, data.target_entry_id,
        data.relation_type, data.description,
    )
    if not ok:
        raise HTTPException(400, "添加失败，请检查条目ID")
    return {"message": "添加成功"}


@router.delete("/wiki/relation/{relation_id}", dependencies=[Depends(get_current_user)])
async def wiki_remove_relation(relation_id: int):
    """删除交叉引用"""
    ok = wiki_service.remove_relation(relation_id)
    if not ok:
        raise HTTPException(404, "关系不存在")
    return {"message": "删除成功"}
