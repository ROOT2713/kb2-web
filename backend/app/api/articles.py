"""Article extraction endpoints — extract knowledge by topic.

OKF P0-6: /api/articles/extract 端点。
P2-3: 接入检索 pipeline (BM25+Dense+RRF)。

与 /api/query 的区别：
- query: 返回 top-K 片段，适合快速问答
- extract: 返回完整知识条目，适合深度研究
"""

import asyncio
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
    page: int = 1
    page_size: int = 20
    summarize: bool = False

    @field_validator("topic")
    @classmethod
    def topic_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("topic 不能为空")
        return v.strip()


@router.post("/extract")
async def extract_by_topic(
    req: ExtractRequest,
    db: Session = Depends(get_db),
):
    """提取特定主题的所有相关内容。

    P2-3: 混合检索策略。

    流程：
    1. BM25 搜索 concepts（SQLite FTS / LIKE）
    2. Dense 搜索 Hindsight（语义召回，可选）
    3. 按 document 聚合 + 过滤
    4. 按 confidence + relevance 排序
    5. 组装为结构化输出
    """
    from app.services.retrieval import recall

    topic = req.topic
    bank = req.bank if req.bank and req.bank != "all" else "kb"

    # Step 1: BM25 搜索 concepts（使用 LIKE 作为 SQLite BM25 的简化实现）
    like_pattern = f"%{topic}%"
    concepts = db.query(Concept).filter(
        Concept.status == "active",
        or_(
            Concept.title.like(like_pattern),
            Concept.summary.like(like_pattern),
            Concept.content.like(like_pattern),
        ),
    ).all()

    bm25_doc_ids = {c.doc_id for c in concepts}

    # Step 2: Dense 搜索 Hindsight（语义召回）
    dense_doc_ids = set()
    try:
        dense_results = await recall(topic, limit=req.limit * 2, bank=bank)
        for r in dense_results:
            for tag in r.get("tags", []):
                if tag.startswith("doc_id:"):
                    dense_doc_ids.add(tag[7:])
    except Exception as e:
        logger.warning("Dense recall failed (non-critical): %s", e)

    # Step 3: 合并结果（BM25 + Dense）
    all_doc_ids = bm25_doc_ids | dense_doc_ids

    # Step 4: 按 document 聚合
    doc_groups = defaultdict(list)
    if all_doc_ids:
        concepts = db.query(Concept).filter(
            Concept.doc_id.in_(list(all_doc_ids)),
            Concept.status == "active",
        ).all()
        for concept in concepts:
            doc_groups[concept.doc_id].append(concept)

    # Step 2.5: 按 bank 过滤（如果指定了 bank）
    if req.bank and req.bank != "all":
        doc_ids = list(doc_groups.keys())
        if doc_ids:
            docs = db.query(Document).filter(Document.doc_id.in_(doc_ids)).all()
            doc_bank = {d.doc_id: d.bank for d in docs}
            doc_groups = {
                k: v for k, v in doc_groups.items()
                if doc_bank.get(k) == req.bank
            }

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

    # Step 5: 分页
    total_results = len(ranked)
    page = max(1, req.page)
    page_size = max(1, min(req.page_size, 100))
    total_pages = max(1, (total_results + page_size - 1) // page_size)
    offset = (page - 1) * page_size
    page_items = ranked[offset:offset + page_size]

    # 批量获取文档元数据（避免 N+1 查询）
    doc_ids = [doc_id for doc_id, _ in page_items]
    docs_map = {}
    if doc_ids:
        docs = db.query(Document).filter(Document.doc_id.in_(doc_ids)).all()
        docs_map = {d.doc_id: d for d in docs}

    extracted = []
    for doc_id, doc_concepts in page_items:
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

    # Step 6: LLM 摘要 (P2 Step 3b)
    summary = ""
    if req.summarize and extracted:
        try:
            from app.services.generation import chat
            summary_texts = []
            for e in extracted[:5]:
                snippet = (e.get("title") or "") + ": " + " ".join(
                    c.get("summary", "") or c.get("title", "")
                    for c in e.get("concepts", [])[:3]
                )
                if snippet.strip():
                    summary_texts.append(snippet[:300])
            if summary_texts:
                prompt = (
                    "请用中文对以下知识库提取结果生成一段简短摘要（不超过500字），"
                    "概括主要主题和关键内容：\n\n"
                    + "\n---\n".join(summary_texts)
                )
                summary = await asyncio.wait_for(
                    chat(messages=[{"role": "user", "content": prompt}], max_tokens=500),
                    timeout=10,
                )
                summary = summary.strip()[:500]
        except asyncio.TimeoutError:
            logger.warning("LLM summary timed out after 10s")
        except Exception as e:
            logger.warning("LLM summary failed (non-critical): %s", e)

    return {
        "topic": topic,
        "total_documents": len(extracted),
        "total_concepts": sum(e["concept_count"] for e in extracted),
        "results": extracted,
        "summary": summary,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_results,
            "total_pages": total_pages,
        },
    }


@router.get("/by-concept")
def extract_by_concept(
    concept_id: str = Query(..., description="Concept ID 前缀"),
    limit: int = Query(50, ge=1, le=500, description="返回结果数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
):
    """按 concept_id 前缀获取相关 concepts。"""
    base = db.query(Concept).filter(
        Concept.concept_id.like(f"{concept_id}%"),
        Concept.status == "active",
    ).order_by(Concept.confidence.desc())

    total = base.count()
    concepts = base.offset(offset).limit(limit).all()

    # 按文档聚合
    doc_groups = defaultdict(list)
    for c in concepts:
        doc_groups[c.doc_id].append(c)

    # 批量获取文档元数据（避免 N+1 查询）
    doc_ids = list(doc_groups.keys())
    docs_map = {}
    if doc_ids:
        docs = db.query(Document).filter(Document.doc_id.in_(doc_ids)).all()
        docs_map = {d.doc_id: d for d in docs}

    results = []
    for doc_id, doc_concepts in doc_groups.items():
        doc = docs_map.get(doc_id)
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
        "pagination": {
            "page": offset // limit + 1 if limit > 0 else 1,
            "page_size": limit,
            "total": total,
            "total_pages": max(1, (total + limit - 1) // limit) if limit > 0 else 1,
        },
    }
