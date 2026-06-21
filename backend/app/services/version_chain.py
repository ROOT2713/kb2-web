"""OKF Version Chain — 文档版本链管理。

P1-1: 当上传新版本文档时，自动标记旧版本为 superseded。
支持同名/同标准号检测、版本历史查询、手动 supersede。

设计原则：
- 一个文档同一时间只有一个 active 版本
- superseded 版本保留数据（不删除），但 status 改为 superseded
- 通过 superseded_by / supersedes 字段形成双向链
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.document import Document

logger = logging.getLogger(__name__)


def detect_existing_doc(
    db: Session,
    title: str,
    bank: str = "general",
    doc_type: str = "generic",
    content_hash: str = "",
) -> Optional[Document]:
    """检测是否已存在同名/同标准号的活跃文档。

    匹配规则（按优先级）：
    1. content_hash 完全匹配（同一文件重新上传）
    2. 同 bank + 同标准号（GB 标准号提取）
    3. 同 bank + 同标题

    Returns:
        匹配到的已有文档，或 None
    """
    # 规则 1: content_hash 精确匹配
    if content_hash:
        existing = db.query(Document).filter(
            Document.content_hash == content_hash,
            Document.status == "active",
        ).first()
        if existing:
            logger.info("Found existing doc by content_hash: %s", existing.doc_id[:8])
            return existing

    # 规则 2: 同 bank + 同标准号
    if doc_type == "gb_standard":
        std_num = _extract_standard_number(title)
        if std_num:
            # 搜索同 bank 下所有活跃文档，匹配标准号
            candidates = db.query(Document).filter(
                Document.bank == bank,
                Document.status == "active",
                Document.doc_type == "gb_standard",
            ).all()
            for c in candidates:
                c_std = _extract_standard_number(c.title or "")
                if c_std and c_std == std_num:
                    logger.info("Found existing doc by standard number: %s", c.doc_id[:8])
                    return c

    # 规则 3: 同 bank + 同标题（精确匹配）
    existing = db.query(Document).filter(
        Document.bank == bank,
        Document.title == title,
        Document.status == "active",
    ).first()
    if existing:
        logger.info("Found existing doc by title: %s", existing.doc_id[:8])
        return existing

    return None


def mark_superseded(
    db: Session,
    old_doc_id: str,
    new_doc_id: str,
    reason: str = "new_version",
) -> bool:
    """标记旧文档为 superseded，并建立双向链接。

    Args:
        db: 数据库 session
        old_doc_id: 被替代的文档 ID
        new_doc_id: 新版本文档 ID
        reason: supersede 原因

    Returns:
        是否成功标记
    """
    old_doc = db.query(Document).filter(Document.doc_id == old_doc_id).first()
    new_doc = db.query(Document).filter(Document.doc_id == new_doc_id).first()

    if not old_doc or not new_doc:
        logger.warning("Document not found: old=%s, new=%s", old_doc_id, new_doc_id)
        return False

    if old_doc.doc_id == new_doc.doc_id:
        logger.warning("Cannot supersede document with itself: %s", old_doc_id)
        return False

    # 标记旧文档
    old_doc.status = "superseded"
    old_doc.superseded_by = new_doc_id
    old_doc.stale_at = datetime.now(timezone.utc)
    old_doc.stale_reason = reason

    # 建立新文档的反向链接
    new_doc.supersedes = old_doc_id

    # 将旧文档的所有 concepts 标记为 superseded
    _supersede_concepts(db, old_doc_id)

    logger.info("Marked doc %s as superseded by %s (reason: %s)",
                old_doc_id[:8], new_doc_id[:8], reason)

    return True


def get_version_history(
    db: Session,
    doc_id: str,
) -> Dict:
    """获取文档的版本历史链。

    Returns:
        {
            "current": {...},           # 当前文档信息
            "superseded_by": {...},     # 替代它的新版本（如果有）
            "supersedes": {...},        # 它替代的旧版本（如果有）
            "chain": [...],             # 完整版本链（从最新到最旧）
        }
    """
    doc = db.query(Document).filter(Document.doc_id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}

    result = {
        "current": _doc_brief(doc),
        "superseded_by": None,
        "supersedes": None,
        "chain": [],
    }

    # 向上查找（谁替代了我）
    if doc.superseded_by:
        newer = db.query(Document).filter(Document.doc_id == doc.superseded_by).first()
        if newer:
            result["superseded_by"] = _doc_brief(newer)

    # 向下查找（我替代了谁）
    if doc.supersedes:
        older = db.query(Document).filter(Document.doc_id == doc.supersedes).first()
        if older:
            result["supersedes"] = _doc_brief(older)

    # 构建完整版本链（从当前文档出发，向两端遍历）
    chain = [_doc_brief(doc)]

    # 向旧版本方向遍历
    current = doc
    while current.supersedes:
        older = db.query(Document).filter(Document.doc_id == current.supersedes).first()
        if not older:
            break
        chain.append(_doc_brief(older))
        current = older

    # 向新版本方向遍历
    current = doc
    while current.superseded_by:
        newer = db.query(Document).filter(Document.doc_id == current.superseded_by).first()
        if not newer:
            break
        chain.insert(0, _doc_brief(newer))
        current = newer

    result["chain"] = chain
    return result


def _extract_standard_number(title: str) -> Optional[str]:
    """从标题提取标准号（GB/T 50116-2013 → gb-t-50116-2013）。"""
    m = re.search(r'(GB[/]?[TSC]?\s*[\d]+(?:\.\d+)?(?:-[\d]+)?)', title)
    if m:
        std_num = re.sub(r'[/\s]+', '-', m.group(1)).lower()
        std_num = re.sub(r'-{2,}', '-', std_num).strip('-')
        return std_num
    return None


def _supersede_concepts(db: Session, doc_id: str):
    """将文档的所有 concepts 标记为 superseded。"""
    from app.models.concept import Concept

    concepts = db.query(Concept).filter(
        Concept.doc_id == doc_id,
        Concept.status == "active",
    ).all()

    for c in concepts:
        c.status = "superseded"

    if concepts:
        logger.info("Superseded %d concepts for doc %s", len(concepts), doc_id[:8])


def _doc_brief(doc: Document) -> Dict:
    """文档简要信息。"""
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "version": doc.version,
        "status": doc.status,
        "bank": doc.bank,
        "doc_type": doc.doc_type,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
