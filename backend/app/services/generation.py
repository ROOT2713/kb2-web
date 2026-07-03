"""LLM generation service — chat completion + logic validation.

Ported from: kb-web server.py deepseek_chat() L1250-L1303, logic_validate() L1164-L1249
"""

import re
import asyncio
import logging
from typing import List, Dict, Optional

import httpx

from app.config import settings
from app.services.cost_tracker import record_call

logger = logging.getLogger(__name__)


# ── LLM Chat ────────────────────────────────────────────────────────────────

async def chat(
    messages: List[Dict],
    stream: bool = False,
    max_retries: int = 3,
    temperature: float = 0.3,
    max_tokens: int = 4000,
) -> str:
    """
    调用 LLM Chat API（带 429 重试）

    Args:
        messages: OpenAI 格式的消息列表
        stream: 是否流式返回
        max_retries: 最大重试次数
        temperature: 温度参数
        max_tokens: 最大输出 token 数

    Returns:
        模型输出文本

    Raises:
        ValueError: API 返回异常
    """
    if not settings.llm_base_url or not settings.llm_api_key:
        raise ValueError("LLM_BASE_URL 或 LLM_API_KEY 未配置")

    last_error = None
    for attempt in range(max_retries):
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            resp = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": stream,
                },
            )
            if stream:
                return resp

            # 429 限流 → 等待重试
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
                logger.warning("LLM API 429 限流, 第%d次重试, 等待 %ds", attempt + 1, retry_after)
                await asyncio.sleep(retry_after)
                continue

            data = resp.json()
            # API 容错：choices 字段缺失或格式异常
            choices = data.get("choices")
            if not choices:
                error_info = data.get("error", {})
                error_msg = error_info.get("message", "") if isinstance(error_info, dict) else str(error_info)
                error_code = error_info.get("code", "") if isinstance(error_info, dict) else ""
                # 429 也可能在 JSON body 中
                if error_code == "429" or "limit" in error_msg.lower():
                    wait = 5 * (attempt + 1)
                    logger.warning("LLM API rate limit in body, 第%d次重试, 等待 %ds", attempt + 1, wait)
                    await asyncio.sleep(wait)
                    continue
                logger.warning("LLM API 无 choices. status=%d error=%s", resp.status_code, error_msg)
                raise ValueError(f"LLM API 返回异常: {error_msg or resp.text[:200]}")

            try:
                # ── Cost tracking ──
                usage = data.get("usage", {})
                if usage:
                    try:
                        record_call(
                            model=settings.llm_model,
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            source="chat",
                        )
                    except Exception as e:
                        logger.warning("cost_tracker failed: %s", e)

                content = choices[0]["message"]["content"]
                # reasoning model: content 可能为空，检查 reasoning_content
                if not content and choices[0]["message"].get("reasoning_content"):
                    content = choices[0]["message"]["reasoning_content"]
                return content or "（模型返回空内容）"
            except (KeyError, IndexError, TypeError) as e:
                logger.warning("LLM API choices 格式异常: %s", e)
                raise ValueError(f"LLM API choices 格式异常: {e}")

    raise ValueError(f"LLM API 重试 {max_retries} 次后仍失败: {last_error or 'rate limit'}")


async def stream_chat(messages: List[Dict]):
    """
    流式聊天 — 返回 httpx.Response 对象，调用者遍历 resp.aiter_lines()
    """
    return await chat(messages, stream=True)


# ── 逻辑校验 ────────────────────────────────────────────────────────────────

def logic_validate(answer: str, context: str, sources: list) -> dict:
    """
    逻辑校验：检查答案与来源的一致性

    检查维度：
    1. 数字一致性 — 答案中的有意义数字是否在 context 中出现
    2. 标准号一致性 — 答案引用的标准号是否在 context 中
    3. 条件限定 — "建议" 不应被升级为 "必须"

    Returns:
        {"issues": [...], "score": 0-100}
    """
    issues = []

    # 1. 数字一致性检查
    answer_numbers = set(re.findall(r'\d+\.?\d*', answer))
    context_numbers = set(re.findall(r'\d+\.?\d*', context))

    def is_meaningful(n):
        """判断数字是否有检查价值"""
        try:
            val = float(n)
        except ValueError:
            return False
        if val < 100:
            return False
        if 1990 <= val <= 2030:
            return False
        if val >= 100 and val == int(val) and val % 100 == 0:
            return False
        if '.' in n and n.endswith('.0'):
            return False
        return True

    meaningful_answer_nums = {n for n in answer_numbers if is_meaningful(n)}
    meaningful_context_nums = {n for n in context_numbers if is_meaningful(n)}

    orphan_numbers = meaningful_answer_nums - meaningful_context_nums
    if orphan_numbers:
        orphan_numbers = {n for n in orphan_numbers
                         if not (2020 <= float(n) <= 2030)}
        if orphan_numbers:
            issues.append({
                "type": "number_mismatch",
                "severity": "high",
                "detail": f"答案中出现来源未提及的数字: {', '.join(sorted(orphan_numbers)[:5])}",
                "fix": "请确认这些数字是否有文档依据，如无则删除"
            })

    # 2. 标准号检查
    answer_standards = set(re.findall(r'GB[/\\]T?\s*\d+[.\-]\d+|T/EGAG\s*\d+[.\-]\d+', answer))
    context_standards = set(re.findall(r'GB[/\\]T?\s*\d+[.\-]\d+|T/EGAG\s*\d+[.\-]\d+', context))

    orphan_standards = answer_standards - context_standards
    if orphan_standards:
        issues.append({
            "type": "standard_mismatch",
            "severity": "critical",
            "detail": f"答案引用了来源未提及的标准: {', '.join(orphan_standards)}",
            "fix": "请删除或替换为文档中实际引用的标准"
        })

    # 3. 条件限定检查
    if "建议" in context and ("必须" in answer or "应当" in answer):
        if "必须" not in context and "应当" not in context and "要求" not in context:
            issues.append({
                "type": "condition_escalation",
                "severity": "medium",
                "detail": "文档中仅为'建议'，但答案表述为'必须/应当'",
                "fix": "请将'必须/应当'改为'建议'"
            })

    # 4. 计算质量分
    score = 100
    for issue in issues:
        if issue["severity"] == "critical":
            score -= 30
        elif issue["severity"] == "high":
            score -= 15
        elif issue["severity"] == "medium":
            score -= 5

    return {"issues": issues, "score": max(0, score)}
