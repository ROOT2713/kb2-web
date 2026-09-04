"""LLM generation service — chat completion + logic validation.

Ported from: kb-web server.py deepseek_chat() L1250-L1303, logic_validate() L1164-L1249
"""

import re
import asyncio
import logging
import time
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
    budget_s: Optional[float] = None,
) -> str:
    """
    调用 LLM Chat API（带 429 重试 + 【R3-2】总预算钳制）

    Args:
        messages: OpenAI 格式的消息列表
        stream: 是否流式返回
        max_retries: 最大重试次数
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        budget_s: 整条重试链的总时间预算（秒）；默认取 settings.chat_retry_budget_s。
            单次调用 timeout 钳在 min(llm_timeout, 剩余预算)；预算耗尽立即放弃，
            不再发起下一次重试——防 3×60s+退避 ≈283s 白烧配额且客户端已超时。

    Returns:
        模型输出文本

    Raises:
        ValueError: API 返回异常 / 预算耗尽仍失败
    """
    if not settings.llm_base_url or not settings.llm_api_key:
        raise ValueError("LLM_BASE_URL 或 LLM_API_KEY 未配置")

    budget = budget_s if budget_s is not None else settings.chat_retry_budget_s
    deadline = time.monotonic() + budget
    last_error = None
    for attempt in range(max_retries):
        # 【R3-2】预算耗尽 → 不再发起下一次，直接失败路径
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning(
                "LLM API chat budget exhausted (%.0fs), giving up after %d attempts",
                budget, attempt,
            )
            break
        # 【FIX-R2-1】网络层异常（超时/连接失败）必须捕获重试——此前 httpx.ReadTimeout/
        # ConnectError 直接冒泡 → 调用方只捕 ValueError → 整请求 500（fee+all 500 根因）
        try:
            async with httpx.AsyncClient(timeout=min(settings.llm_timeout, remaining)) as client:
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
        except httpx.HTTPError as e:
            last_error = e
            logger.warning(
                "LLM API 网络异常 %s (attempt %d/%d), %ds 后重试",
                type(e).__name__, attempt + 1, max_retries, min(2 ** attempt, 15),
            )
            if attempt < max_retries - 1:
                backoff = min(2 ** attempt, 15)
                # 【R3-2】退避后会穿预算 → 直接放弃，不再 sleep
                if time.monotonic() + backoff >= deadline:
                    break
                await asyncio.sleep(backoff)
                continue
            break  # 重试耗尽 → 落到循环外 raise ValueError(last_error)

        # 429 限流 → 等待重试
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
            logger.warning("LLM API 429 限流, 第%d次重试, 等待 %ds", attempt + 1, retry_after)
            # 【R3-2】等待会穿预算 → 直接放弃
            if time.monotonic() + retry_after >= deadline:
                last_error = f"HTTP 429 (retry would exceed budget)"
                break
            await asyncio.sleep(retry_after)
            continue

        # 【FIX-R2-1】服务端 5xx（LLM 网关 500/502/503 等临时故障）→ 退避重试
        if resp.status_code >= 500:
            last_error = f"HTTP {resp.status_code}"
            logger.warning(
                "LLM API %d 服务端错误 (attempt %d/%d), %ds 后重试",
                resp.status_code, attempt + 1, max_retries, min(2 ** attempt, 15),
            )
            if attempt < max_retries - 1:
                backoff = min(2 ** attempt, 15)
                # 【R3-2】退避后会穿预算 → 直接放弃
                if time.monotonic() + backoff >= deadline:
                    break
                await asyncio.sleep(backoff)
                continue
            break

        try:
            data = resp.json()
        except ValueError as e:
            # 【FIX-R2-1】非 JSON 响应（网关 HTML 错误页等）→ 重试，不裸抛成 500
            last_error = f"invalid JSON: {e}"
            logger.warning(
                "LLM API 响应非 JSON (attempt %d/%d): %.120s",
                attempt + 1, max_retries, resp.text,
            )
            if attempt < max_retries - 1:
                backoff = min(2 ** attempt, 15)
                # 【R3-2】退避后会穿预算 → 直接放弃
                if time.monotonic() + backoff >= deadline:
                    break
                await asyncio.sleep(backoff)
                continue
            raise ValueError(f"LLM API 返回非 JSON: {resp.text[:200]}")
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
                # 【R3-2】等待会穿预算 → 直接放弃
                if time.monotonic() + wait >= deadline:
                    last_error = "rate limit in body (retry would exceed budget)"
                    break
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
            finish_reason = choices[0].get("finish_reason", "")
            # 铁律：content 为空时绝不使用 reasoning_content（思维链不是答案）。
            # 推理模型 reasoning 会吃满 token 预算 → content 被截断为空（finish_reason=length）
            # → 翻倍 max_tokens 重试（带上限保护）；其余空内容走正常重试/报错。
            if not content and finish_reason == "length":
                if attempt < max_retries - 1:
                    next_mt = min(max_tokens * 2, 16000)
                    logger.warning(
                        "LLM content empty (finish_reason=length), retrying with max_tokens=%d",
                        next_mt,
                    )
                    max_tokens = next_mt
                    continue
            if not content:
                logger.warning("LLM returned empty content (finish_reason=%s), attempt=%d", finish_reason, attempt + 1)
                if attempt < max_retries - 1:
                    continue
                raise ValueError(f"LLM returned empty content after {max_retries} attempts")
            return content

        except (KeyError, IndexError, TypeError) as e:
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

    # 预先从 context 中提取标准号对应的数字，避免误报
    # 例：GB/T 2887-2011 → 2887 为标准编号，不应归入 number_mismatch
    _context_standard_nums: set[str] = set()
    for m in re.finditer(r'GB[/\\]T?\s*(\d+)', context, re.IGNORECASE):
        _context_standard_nums.add(m.group(1))
    for m in re.finditer(r'T/EGAG\s*(\d+)', context, re.IGNORECASE):
        _context_standard_nums.add(m.group(1))

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
        # 排除标准号数字（如 2887、22239、50314 等标准编号）
        orphan_numbers = orphan_numbers - _context_standard_nums
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
