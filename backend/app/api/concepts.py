"""Concept management endpoints — get, search, list by doc.

OKF P0-5: concept 级检索 API。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.concept import Concept
from app.models.document import Document

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/search")
def search_concepts(
    q: str = Query(..., min_length=1, description="搜索关键词（匹配标题/摘要/内容）"),
    doc_id: Optional[str] = Query(None, description="限定文档 ID"),
    status: str = Query("active", description="概念状态过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    db: Session = Depends(get_db),
):
    """搜索 concept — 关键词匹配标题/摘要/内容。

    使用 SQLite LIKE 进行模糊匹配（后续可升级为 FTS5）。
    """
    query = db.query(Concept).filter(Concept.status == status)

    if doc_id:
        query = query.filter(Concept.doc_id == doc_id)

    # 关键词匹配：标题 + 摘要 + 内容
    like_pattern = f"%{q}%"
    query = query.filter(
        or_(
            Concept.title.like(like_pattern),
            Concept.summary.like(like_pattern),
            Concept.content.like(like_pattern),
        )
    )

    # 按 confidence 降序 + access_count 降序排列
    query = query.order_by(
        Concept.confidence.desc(),
        Concept.access_count.desc(),
    )

    total = query.count()
    concepts = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "concepts": [c.to_dict() for c in concepts],
    }


@router.get("/get")
def get_concept(
    concept_id: str = Query(..., description="Concept ID (含斜杠，如 standards/security/gb-50116)"),
    db: Session = Depends(get_db),
):
    """获取单个 concept 详情（含完整内容）。

    使用 query parameter 而非 path parameter，因为 concept_id 含斜杠。
    """
    concept = db.query(Concept).filter(Concept.concept_id == concept_id).first()
    if not concept:
        raise HTTPException(404, f"Concept not found: {concept_id}")

    # 更新访问计数
    from datetime import datetime, timezone
    concept.access_count = (concept.access_count or 0) + 1
    concept.last_accessed_at = datetime.now(timezone.utc)
    db.commit()

    # Phase A: include parent document's review_required + last_confirmed
    result = concept.to_full_dict()
    doc = db.query(Document).filter(Document.doc_id == concept.doc_id).first()
    if doc:
        result["review_required"] = doc.review_required or 0
        if doc.last_confirmed:
            result["last_confirmed"] = doc.last_confirmed.isoformat()

    return result


@router.get("")
def list_concepts(
    doc_id: Optional[str] = Query(None, description="按文档 ID 过滤"),
    status: str = Query("active", description="状态过滤"),
    domain: Optional[str] = Query(None, description="按 domain 过滤（通过 concept_id 前缀匹配）"),
    limit: int = Query(50, ge=1, le=200, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    db: Session = Depends(get_db),
):
    """列出 concept — 支持按文档/状态/域过滤。"""
    query = db.query(Concept).filter(Concept.status == status)

    if doc_id:
        query = query.filter(Concept.doc_id == doc_id)

    if domain:
        # 按 concept_id 前缀匹配 domain
        query = query.filter(Concept.concept_id.like(f"{domain}%"))

    query = query.order_by(Concept.confidence.desc())

    total = query.count()
    concepts = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "concepts": [c.to_dict() for c in concepts],
    }
