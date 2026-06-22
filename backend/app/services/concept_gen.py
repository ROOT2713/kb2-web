"""OKF Concept generation — 从 parent_chunks 生成语义概念单元。

P0-2: 上传时为每个 parent section 生成一个 concept（标题+摘要+内容）。
不依赖 LLM，纯规则提取（后续 P1 可加 LLM summary）。
P0-3: infer_doc_concept_id() — 基于标题/标准号自动分配 doc 级 concept_id。
"""

import logging
import re
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from app.models.concept import Concept

logger = logging.getLogger(__name__)


# ── P0-3: bank → OKF domain 映射（避免循环导入 upload.py）──
_BANK_TO_DOMAIN = {
    "general": "methodology",
    "business": "learning",
    "law": "governance",
    "methodology": "methodology",
    "standard": "standards",
    "tech": "operations",
    "standards": "standards",
    "governance": "governance",
    "operations": "operations",
    "learning": "learning",
    "ephemeral": "ephemeral",
}


def infer_domain(bank: str = "general", doc_type: str = "generic") -> str:
    """从 bank 名 + doc_type 推断 OKF domain（统一逻辑，upload.py 共用）。

    优先级：doc_type (gb_standard/regulation) > bank 映射 > 默认 methodology。
    """
    if doc_type in ("gb_standard", "regulation"):
        return "standards"
    return _BANK_TO_DOMAIN.get(bank, "methodology")


def infer_doc_concept_id(
    title: str,
    bank: str = "general",
    doc_type: str = "generic",
    text: str = "",
) -> Optional[str]:
    """根据标题/标准号/文档类型推断文档级 concept_id。

    返回格式: {domain}/{subdomain}/{slug}
    例如: standards/security/gb-50116, governance/regulation/labor-protection
    """
    domain = _BANK_TO_DOMAIN.get(bank, "methodology")
    if doc_type in ("gb_standard", "regulation"):
        domain = "standards"

    slug = ""
    subdomain = ""

    if doc_type == "gb_standard":
        # 尝试从标题提取标准号: GB/T 50116-2013, GB 50016-2014 等
        m = re.search(r'(GB[/]?[TSC]?\s*[\d]+(?:\.\d+)?(?:-[\d]+)?)', title)
        if m:
            std_num = re.sub(r'[/\s]+', '-', m.group(1)).lower()  # gb-t-50116-2013
            std_num = re.sub(r'-{2,}', '-', std_num).strip('-')
            slug = std_num
        else:
            slug = _title_to_slug(title)
        subdomain = _infer_subdomain(title, text)

    elif doc_type == "regulation":
        slug = _title_to_slug(title)
        subdomain = _infer_subdomain(title, text)

    else:
        slug = _title_to_slug(title)

    if not slug:
        return None

    parts = [domain]
    if subdomain:
        parts.append(subdomain)
    parts.append(slug)
    return "/".join(parts)


def _title_to_slug(title: str) -> str:
    """将标题转为 URL-safe slug（保留中文）。"""
    slug = re.sub(r'[^\w\u4e00-\u9fff]+', '-', title).strip('-').lower()
    slug = re.sub(r'-{2,}', '-', slug)
    return slug[:60] if slug else ""


def _infer_subdomain(title: str, text: str = "") -> str:
    """从标题或文本推断子领域（如 security, laboratory 等）。"""
    combined = (title + " " + text[:500]).lower()
    keywords = {
        "security": ["安全", "消防", "安防", "信息安", "网络安", "防火", "监控", "入侵"],
        "laboratory": ["实验室", "检测", "检验", "校准", "测试"],
        "quality": ["质量", "认证", "审核", "评审", "验收"],
        "environment": ["环境", "环保", "排放", "污染", "生态"],
        "fire": ["消防", "灭火", "火灾", "防火", "报警"],
    }
    for subdomain, kws in keywords.items():
        if any(kw in combined for kw in kws):
            return subdomain
    return ""


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
    m = re.match(r'^(第[一二三四五六七八九十\d]+[章节条款编]|[\d]+\.[\d]+[\.\\d]*\s)', first_line)
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
    doc_id: str = "",
) -> str:
    """为单个 concept 生成唯一 ID。

    格式: {doc_concept_id}/{doc_id-short}/section-{parent_idx}
    doc_id 前缀防止不同文档生成相同 concept_id。
    """
    base = (doc_concept_id or "unknown").rstrip("/")
    # doc_id 前 8 位作为命名空间隔离
    doc_ns = doc_id[:8] if doc_id else "unknown"
    # 清理 title 中的特殊字符用于 slug
    slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', title).strip('-').lower()[:40]
    return f"{base}/{doc_ns}/section-{parent_idx}-{slug}" if slug else f"{base}/{doc_ns}/section-{parent_idx}"


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
        cid = _generate_concept_id(concept_id, idx, title, doc_id)

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
