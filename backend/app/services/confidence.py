"""OKF Confidence 计算 — 多维度知识置信度评分。

P2-1: 基于设计文档的 confidence 公式实现。

confidence = f(source_count, time_decay, access_frequency, contradiction_count)

四个维度：
1. source_count: 多源支撑度（同一事实被多少文档引用）
2. time_decay: 时效性衰减（越久未确认分数越低）
3. access_frequency: 访问频率（被检索命中次数）
4. contradiction_count: 矛盾数（反向扣分）

默认权重：
- source_count: 0.3
- time_decay: 0.4 (最重要)
- access_frequency: 0.2
- contradiction_count: 0.1
"""

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.concept import Concept

logger = logging.getLogger(__name__)

# 权重配置
WEIGHTS = {
    "source_count": 0.3,
    "time_decay": 0.4,
    "access_frequency": 0.2,
    "contradiction": 0.1,
}

# 时间衰减参数
DECAY_HALF_LIFE_DAYS = 180  # 半衰期 180 天
MAX_ACCESS_SCORE = 100  # 访问次数达到此值后满分


def compute_concept_confidence(
    db: Session,
    concept_id: str,
) -> float:
    """计算单个 concept 的置信度。

    Returns:
        0.0 - 1.0 的置信度分数
    """
    concept = db.query(Concept).filter(Concept.concept_id == concept_id).first()
    if not concept:
        return 0.0

    doc = db.query(Document).filter(Document.doc_id == concept.doc_id).first()

    scores = {}

    # 维度 1: source_count — 同 concept_id 前缀下有多少活跃概念
    prefix = "/".join(concept_id.split("/")[:3])  # domain/subdomain/slug
    source_count = db.query(Concept).filter(
        Concept.concept_id.like(f"{prefix}%"),
        Concept.status == "active",
    ).count()
    scores["source_count"] = min(source_count / 3.0, 1.0)  # 3 个源满分

    # 维度 2: time_decay — 时间衰减
    scores["time_decay"] = _time_decay_score(concept.updated_at or concept.created_at)

    # 维度 3: access_frequency — 访问频率
    access = concept.access_count or 0
    scores["access_frequency"] = min(access / MAX_ACCESS_SCORE, 1.0)

    # 维度 4: contradiction — 矛盾数（暂无实现，返回 1.0）
    scores["contradiction"] = 1.0  # TODO: 检测矛盾

    # 加权计算
    confidence = sum(
        scores[dim] * WEIGHTS[dim]
        for dim in WEIGHTS
    )

    return round(min(max(confidence, 0.0), 1.0), 4)


def compute_document_confidence(
    db: Session,
    doc_id: str,
) -> float:
    """计算文档级置信度（所有 concept 的平均）。"""
    concepts = db.query(Concept).filter(
        Concept.doc_id == doc_id,
        Concept.status == "active",
    ).all()

    if not concepts:
        return 0.0

    # 获取文档级信号
    doc = db.query(Document).filter(Document.doc_id == doc_id).first()
    doc_scores = {}

    # 文档级 source_count: 同 domain 下有多少文档
    if doc and doc.domain:
        domain_docs = db.query(Document).filter(
            Document.domain == doc.domain,
            Document.status == "active",
        ).count()
        doc_scores["source_count"] = min(domain_docs / 5.0, 1.0)
    else:
        doc_scores["source_count"] = 0.5

    # 文档级 time_decay
    doc_scores["time_decay"] = _time_decay_score(
        doc.updated_at if doc else None
    )

    # 文档级 access
    doc_scores["access_frequency"] = 0.5  # 暂用默认值

    doc_scores["contradiction"] = 1.0

    doc_confidence = sum(
        doc_scores[dim] * WEIGHTS[dim]
        for dim in WEIGHTS
    )

    # 概念级平均
    concept_avg = sum(c.confidence or 0.5 for c in concepts) / len(concepts)

    # 最终 = 0.4 * 文档级 + 0.6 * 概念级
    final = 0.4 * doc_confidence + 0.6 * concept_avg

    return round(min(max(final, 0.0), 1.0), 4)


def update_concept_confidence(
    db: Session,
    concept_id: str,
    persist: bool = True,
) -> float:
    """重新计算并更新 concept 的 confidence。"""
    new_conf = compute_concept_confidence(db, concept_id)

    if persist:
        concept = db.query(Concept).filter(Concept.concept_id == concept_id).first()
        if concept:
            concept.confidence = new_conf
            db.flush()

    # Phase A: always sync doc.review_required based on current doc-level min
    _flag_doc_for_review(db, concept_id)

    return new_conf


def update_all_confidences(
    db: Session,
    batch_size: int = 100,
) -> Dict:
    """批量重算所有 concept 的 confidence。"""
    total = 0
    updated = 0

    concepts = db.query(Concept).filter(
        Concept.status == "active",
    ).all()

    for concept in concepts:
        new_conf = compute_concept_confidence(db, concept.concept_id)
        if abs(new_conf - (concept.confidence or 0)) > 0.01:
            concept.confidence = new_conf
            updated += 1
        total += 1

        # Phase A: always sync doc.review_required based on current doc-level min
        _flag_doc_for_review(db, concept.concept_id)

        if total % batch_size == 0:
            db.flush()

    db.flush()

    unchanged = total - updated
    return {
        "total": total,
        "updated": unchanged,
        "changed": updated,
    }


def _flag_doc_for_review(db: Session, concept_id: str):
    """Sync review_required on the document that owns this concept.

    Phase A semantics: review_required reflects the doc-level minimum
    concept confidence. If ANY concept on this doc has confidence < 0.7,
    set 1; if ALL concepts are >= 0.7, clear to 0.
    """
    concept = db.query(Concept).filter(Concept.concept_id == concept_id).first()
    if not concept:
        return
    doc = db.query(Document).filter(Document.doc_id == concept.doc_id).first()
    if not doc or doc.status != "active":
        return

    # Compute doc-level min confidence across all active concepts
    min_conf = db.query(func.min(Concept.confidence)).filter(
        Concept.doc_id == doc.doc_id,
        Concept.status == "active",
    ).scalar()

    new_flag = 1 if (min_conf is not None and min_conf < 0.7) else 0
    if doc.review_required != new_flag:
        doc.review_required = new_flag
        db.flush()
        logger.info("Sync doc %s review_required=%d (min concept conf=%s)",
                    doc.doc_id[:8], new_flag, min_conf)


def _time_decay_score(dt: Optional[datetime]) -> float:
    """时间衰减评分：基于指数衰减。"""
    if not dt:
        return 0.5  # 未知时间给中等分

    now = datetime.now(timezone.utc)
    # 处理 naive datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    days_old = (now - dt).days
    # 指数衰减: score = 2^(-days/half_life)
    score = math.pow(2, -days_old / DECAY_HALF_LIFE_DAYS)
    return min(max(score, 0.0), 1.0)


def get_confidence_summary(db: Session) -> Dict:
    """获取 confidence 统计摘要。"""
    concepts = db.query(Concept).filter(
        Concept.status == "active"
    ).all()

    if not concepts:
        return {"total": 0, "avg": 0, "distribution": {}}

    confs = [c.confidence or 0.5 for c in concepts]
    avg = sum(confs) / len(confs)

    # 分布统计
    dist = {"high (>0.7)": 0, "medium (0.3-0.7)": 0, "low (<0.3)": 0}
    for c in confs:
        if c > 0.7:
            dist["high (>0.7)"] += 1
        elif c > 0.3:
            dist["medium (0.3-0.7)"] += 1
        else:
            dist["low (<0.3)"] += 1

    return {
        "total": len(concepts),
        "avg": round(avg, 4),
        "min": round(min(confs), 4),
        "max": round(max(confs), 4),
        "distribution": dist,
    }
