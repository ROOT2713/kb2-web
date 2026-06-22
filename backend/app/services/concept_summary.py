"""OKF Concept Summary — LLM 概念摘要生成。

P2-2: 为每个 concept 生成 1-3 句精炼摘要。

设计：
- 使用 DeepSeek Chat API 生成摘要
- 批量处理，避免频繁调用
- 失败时保留空摘要（不影响主流程）
"""

import asyncio
import json
import logging
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from app.models.concept import Concept

logger = logging.getLogger(__name__)


async def generate_summary(
    content: str,
    title: str = "",
    max_length: int = 200,
) -> str:
    """调用 LLM 生成单条摘要。

    Args:
        content: 原文内容（截取前 2000 字符避免超长）
        title: 概念标题（可选，帮助 LLM 理解上下文）
        max_length: 摘要最大长度

    Returns:
        1-3 句摘要文本
    """
    from app.services.generation import chat

    # 截取内容避免超长
    truncated = content[:2000] if content else ""

    prompt = f"""请为以下知识概念生成一段简洁的摘要（1-3句话，不超过{max_length}字）。

标题: {title or '(无标题)'}

内容:
{truncated}

要求:
1. 提取核心要点
2. 使用客观陈述
3. 不要添加标题或编号
4. 直接输出摘要内容"""

    try:
        messages = [
            {"role": "system", "content": "你是一个专业的知识库摘要生成器。请用简洁准确的中文生成摘要。"},
            {"role": "user", "content": prompt},
        ]
        result = await chat(messages, max_tokens=max_length)
        summary = result.strip()
        # 清理可能的前缀
        for prefix in ["摘要:", "摘要：", "Answer:", "回答:"]:
            if summary.startswith(prefix):
                summary = summary[len(prefix):].strip()
        return summary[:max_length]
    except Exception as e:
        logger.warning("Failed to generate summary: %s", e)
        return ""


async def generate_summaries_batch(
    db: Session,
    doc_id: str,
    limit: int = 20,
) -> int:
    """为单个文档的所有 concept 批量生成摘要。

    Returns:
        成功生成摘要的 concept 数量
    """
    concepts = db.query(Concept).filter(
        Concept.doc_id == doc_id,
        Concept.status == "active",
        (Concept.summary == None) | (Concept.summary == ""),
    ).limit(limit).all()

    if not concepts:
        return 0

    count = 0
    for concept in concepts:
        try:
            summary = await generate_summary(
                content=concept.content or "",
                title=concept.title or "",
            )
            if summary:
                concept.summary = summary
                count += 1
        except Exception as e:
            logger.warning("Summary gen failed for %s: %s", concept.concept_id, e)

        # 避免 rate limit
        await asyncio.sleep(0.5)

    db.flush()
    logger.info("Generated summaries for %d/%d concepts in doc %s", count, len(concepts), doc_id[:8])
    return count


async def generate_all_summaries(
    db: Session,
    limit: int = 100,
) -> Dict:
    """批量为所有无摘要的 concept 生成摘要。"""
    concepts = db.query(Concept).filter(
        Concept.status == "active",
        (Concept.summary == None) | (Concept.summary == ""),
    ).limit(limit).all()

    if not concepts:
        return {"total": 0, "generated": 0}

    count = 0
    for i, concept in enumerate(concepts):
        try:
            summary = await generate_summary(
                content=concept.content or "",
                title=concept.title or "",
            )
            if summary:
                concept.summary = summary
                count += 1
        except Exception as e:
            logger.warning("Summary gen failed for %s: %s", concept.concept_id, e)

        # 每 10 个 flush 一次
        if (i + 1) % 10 == 0:
            db.flush()

        # Rate limit
        await asyncio.sleep(0.3)

    db.flush()
    return {"total": len(concepts), "generated": count}
