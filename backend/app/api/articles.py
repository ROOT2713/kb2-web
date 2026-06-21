"""Article extraction endpoints — extract knowledge by topic.

OKF P0-6: /api/articles/extract 端点。
与 /api/query 的区别：
- query: 返回 top-K 片段，适合快速问答
- extract: 返回完整知识条目，适合深度研究
"""

import logging
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.concept import Concept
from app.models.document import Document

logger = logging.getLogger(__name__)

router = APIRouter()



class ExtractRequest(BaseModel):
    topic: str
    bank: Optional[str] = "all"
    include_stale: bool = False
    min_confidence: float = 0.0
    limit: int = 50

    @field_validator("topic")
    @classmethod
    def topic_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("topic 不能为空")
        return v.strip()


@router.post("/extract")
def extract_by_topic(
    req: ExtractRequest,
    db: Session = Depends(get_db),
):
    """提取特定主题的所有相关内容。

    流程：
    1. 按关键词搜索 concepts
    2. 按 document 聚合
    3. 过滤 (stale, confidence)
    4. 按 confidence + relevance 排序
    5. 组装为结构化输出
    """
    topic = req.topic

    # Step 1: 搜索 concepts（关键词匹配标题/摘要/内容）
    like_pattern = f"%{topic}%"
    query = db.query(Concept).filter(
        Concept.status == "active",
        or_(
            Concept.title.like(like_pattern),
            Concept.summary.like(like_pattern),
            Concept.content.like(like_pattern),
        ),
    )

    concepts = query.all()

    # Step 2: 按 document 聚合
    doc_groups = defaultdict(list)
    for concept in concepts:
        doc_groups[concept.doc_id].append(concept)

    # Step 3: 过滤
    if not req.include_stale:
        # 获取文档状态
        doc_ids = list(doc_groups.keys())
        if doc_ids:
            docs = db.query(Document).filter(Document.doc_id.in_(doc_ids)).all()
            doc_status = {d.doc_id: d.status for d in docs}
            doc_groups = {
                k: v for k, v in doc_groups.items()
                if doc_status.get(k, "active") != "deprecated"
            }

    if req.min_confidence > 0:
        doc_groups = {
            k: v for k, v in doc_groups.items()
            if any(c.confidence >= req.min_confidence for c in v)
        }

    # Step 4: 排序（按平均 confidence 降序）
    def _doc_score(item):
        doc_id, concepts = item
        avg_conf = sum(c.confidence or 0 for c in concepts) / len(concepts) if concepts else 0
        total_access = sum(c.access_count or 0 for c in concepts)
        return (avg_conf, total_access)

    ranked = sorted(doc_groups.items(), key=_doc_score, reverse=True)

    # Step 5: 组装输出
    # 批量获取文档元数据（避免 N+1 查询）
    doc_ids = [doc_id for doc_id, _ in ranked[:req.limit]]
    docs_map = {}
    if doc_ids:
        docs = db.query(Document).filter(Document.doc_id.in_(doc_ids)).all()
        docs_map = {d.doc_id: d for d in docs}

    extracted = []
    for doc_id, doc_concepts in ranked[:req.limit]:
        doc = docs_map.get(doc_id)
        title = doc.title if doc else ""
        domain = doc.domain if doc else ""

        avg_conf = sum(c.confidence or 0 for c in doc_concepts) / len(doc_concepts)

        extracted.append({
            "doc_id": doc_id,
            "title": title,
            "domain": domain,
            "confidence": round(avg_conf, 3),
            "concept_count": len(doc_concepts),
            "concepts": [
                {
                    "concept_id": c.concept_id,
                    "title": c.title,
                    "summary": c.summary,
                    "confidence": c.confidence,
                    "access_count": c.access_count,
                }
                for c in sorted(doc_concepts, key=lambda x: x.confidence or 0, reverse=True)
            ],
            "total_chars": sum(len(c.content or "") for c in doc_concepts),
        })

    return {
        "topic": topic,
        "total_documents": len(extracted),
        "total_concepts": sum(e["concept_count"] for e in extracted),
        "results": extracted,
    }


@router.get("/by-concept")
def extract_by_concept(
    concept_id: str = Query(..., description="Concept ID 前缀"),
    db: Session = Depends(get_db),
):
    """按 concept_id 前缀获取相关 concepts。"""
    concepts = db.query(Concept).filter(
        Concept.concept_id.like(f"{concept_id}%"),
        Concept.status == "active",
    ).order_by(Concept.confidence.desc()).all()

    # 按文档聚合
    doc_groups = defaultdict(list)
    for c in concepts:
        doc_groups[c.doc_id].append(c)

    results = []
    for doc_id, doc_concepts in doc_groups.items():
        doc = db.query(Document).filter(Document.doc_id == doc_id).first()
        results.append({
            "doc_id": doc_id,
            "title": doc.title if doc else "",
            "concepts": [c.to_dict() for c in doc_concepts],
        })

    return {
        "concept_prefix": concept_id,
        "total_documents": len(results),
        "total_concepts": len(concepts),
        "results": results,
    }
