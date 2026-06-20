"""OKF Concept generation — 从 parent_chunks 生成语义概念单元。

P0-2: 上传时为每个 parent section 生成一个 concept（标题+摘要+内容）。
不依赖 LLM，纯规则提取（后续 P1 可加 LLM summary）。
"""

import logging
import re
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from app.models.concept import Concept

logger = logging.getLogger(__name__)


def _extract_section_title(parent_text: str, doc_type: str = "generic") -> str:
    """从 parent_text 提取章节标题。

    规则：
    1. 首行如果是 # 标题 → 取标题文字
    2. 首行如果是 "第X章/节/条" 格式 → 取该行
    3. 首行如果是 GB 标准的条款号 (如 "4.1.2 xxx") → 取该行
    4. 否则取前 80 字符
    """
    lines = parent_text.strip().split("\n")
    first_line = lines[0].strip() if lines else ""

    # Markdown heading
    m = re.match(r'^#{1,6}\s+(.+)', first_line)
    if m:
        return m.group(1).strip()[:120]

    # Chinese chapter/section markers
    m = re.match(r'^(第[一二三四五六七八九十\d]+[章节条款编]|[\d]+\.[\d]+[\.\d]*\s)', first_line)
    if m:
        return first_line[:120]

    # GB standard clause numbers (e.g., "4.1", "5.2.3")
    m = re.match(r'^(\d+\.\d+(?:\.\d+)?)\s+(.+)', first_line)
    if m:
        return first_line[:120]

    # Fallback: first 80 chars
    return first_line[:80] if first_line else "(untitled section)"


def _generate_concept_id(
    doc_concept_id: Optional[str],
    parent_idx: int,
    title: str,
) -> str:
    """为单个 concept 生成唯一 ID。

    格式: {doc_concept_id}/section-{parent_idx}
    如果 doc_concept_id 未设置，用 doc_id 前 8 位。
    """
    base = doc_concept_id or "unknown"
    # 清理 title 中的特殊字符用于 slug
    slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', title).strip('-').lower()[:40]
    return f"{base}/section-{parent_idx}-{slug}" if slug else f"{base}/section-{parent_idx}"


def generate_concepts_for_doc(
    db: Session,
    doc_id: str,
    concept_id: Optional[str],
    parent_chunks: List[Dict],
    doc_type: str = "generic",
    confidence: float = 0.5,
) -> int:
    """为文档的每个 parent chunk 生成一个 concept 记录。

    Args:
        db: 数据库 session
        doc_id: 文档 ID
        concept_id: 文档级 concept_id（可为 None）
        parent_chunks: [{"parent_index": int, "parent": str}, ...]
        doc_type: 文档类型
        confidence: 文档级置信度

    Returns:
        生成的 concept 数量
    """
    if not parent_chunks:
        return 0

    count = 0
    for pc in parent_chunks:
        idx = pc.get("parent_index", 0)
        text = pc.get("parent", "")
        if not text or len(text.strip()) < 50:
            continue  # 太短的 section 不生成 concept

        title = _extract_section_title(text, doc_type)
        cid = _generate_concept_id(concept_id, idx, title)

        concept = Concept(
            concept_id=cid,
            doc_id=doc_id,
            parent_idx=idx,
            title=title,
            summary="",  # P1: 用 LLM 生成 1-3 句摘要
            content=text,
            confidence=confidence,
            status="active",
        )
        db.merge(concept)
        count += 1

    if count > 0:
        logger.info("Generated %d concepts for doc %s", count, doc_id)

    return count
