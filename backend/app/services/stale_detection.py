"""OKF Stale Detection — 文档过期检测服务。

P1-2: 定期检查超过 N 天未确认/未更新的文档，标记为 stale。

判定规则：
1. verified_at 超过 max_days → stale（未验证）
2. updated_at 超过 max_days 且无 source_url → stale（长期未更新）
3. 已 superseded 的文档不检测（已经是历史版本）

stale ≠ deprecated：
- stale: 信息可能过时，需要人工确认
- deprecated: 明确废弃，不再使用
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.document import Document

logger = logging.getLogger(__name__)

# 默认阈值
DEFAULT_STALE_DAYS = 90  # 90 天未确认视为 stale


def detect_stale_documents(
    db: Session,
    max_days: int = DEFAULT_STALE_DAYS,
    dry_run: bool = False,
) -> Dict:
    """检测过期文档。

    Args:
        db: 数据库 session
        max_days: 超过此天数未确认视为 stale
        dry_run: 仅检测不修改

    Returns:
        {
            "total_checked": int,
            "stale_count": int,
            "stale_docs": [{"doc_id", "title", "stale_reason", "days_since"}],
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)

    # 查询活跃文档（非 superseded、非 deprecated、非 draft）
    active_docs = db.query(Document).filter(
        Document.status == "active",
    ).all()

    stale_docs = []
    now = datetime.now(timezone.utc)

    for doc in active_docs:
        stale_reason = _check_staleness(doc, cutoff, now)
        if stale_reason:
            days_since = _days_since(doc, now)
            stale_docs.append({
                "doc_id": doc.doc_id,
                "title": doc.title,
                "bank": doc.bank,
                "stale_reason": stale_reason,
                "days_since": days_since,
                "verified_at": doc.verified_at.isoformat() if doc.verified_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            })

            if not dry_run:
                doc.status = "stale"
                doc.stale_at = now
                doc.stale_reason = stale_reason

    if not dry_run and stale_docs:
        db.commit()
        logger.info("Marked %d documents as stale (max_days=%d)", len(stale_docs), max_days)

    return {
        "total_checked": len(active_docs),
        "stale_count": len(stale_docs),
        "stale_docs": stale_docs,
        "max_days": max_days,
        "dry_run": dry_run,
    }


def restore_stale_document(
    db: Session,
    doc_id: str,
) -> bool:
    """恢复 stale 文档为 active。

    人工确认后调用，将 status 改回 active 并清除 stale 信息。
    """
    doc = db.query(Document).filter(Document.doc_id == doc_id).first()
    if not doc or doc.status != "stale":
        return False

    doc.status = "active"
    doc.stale_at = None
    doc.stale_reason = None
    doc.verified_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("Restored doc %s from stale to active", doc_id[:8])
    return True


def get_stale_summary(db: Session) -> Dict:
    """获取 stale 文档统计摘要。"""
    total = db.query(Document).filter(Document.status == "active").count()
    stale = db.query(Document).filter(Document.status == "stale").count()
    superseded = db.query(Document).filter(Document.status == "superseded").count()

    # 按 stale_reason 分组
    stale_docs = db.query(Document).filter(Document.status == "stale").all()
    reasons = {}
    for doc in stale_docs:
        reason = doc.stale_reason or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "active": total,
        "stale": stale,
        "superseded": superseded,
        "total": total + stale + superseded,
        "stale_by_reason": reasons,
    }


def _check_staleness(doc: Document, cutoff: datetime, now: datetime) -> Optional[str]:
    """检查单个文档是否过期，返回 stale 原因或 None。"""

    def _to_aware(dt):
        """将 naive datetime 转为 aware（SQLite 存储为 naive）。"""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    # 规则 1: 从未验证且创建时间超过阈值
    if not doc.verified_at:
        created = _to_aware(doc.created_at or doc.updated_at)
        if created and created < cutoff:
            days = (now - created).days
            return f"never_verified ({days}d since creation)"

    # 规则 2: 最后验证时间超过阈值
    verified = _to_aware(doc.verified_at)
    if verified and verified < cutoff:
        days = (now - verified).days
        return f"verification_expired ({days}d since last verify)"

    # 规则 3: 长期未更新（无 source_url 的本地文档）
    updated = _to_aware(doc.updated_at)
    if not doc.source_url and updated and updated < cutoff:
        days = (now - updated).days
        return f"stale_content ({days}d since last update, no source_url)"

    return None


def _days_since(doc: Document, now: datetime) -> int:
    """计算文档最后活动距今天数。"""

    def _to_aware(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    last_active = _to_aware(doc.verified_at or doc.updated_at or doc.created_at)
    if last_active:
        return (now - last_active).days
    return -1
