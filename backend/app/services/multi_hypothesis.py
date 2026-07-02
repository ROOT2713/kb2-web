"""Multi-hypothesis comparison service.

P2: Generates N parallel answer hypotheses with different LLM perspectives,
then evaluates and selects the best one via a judge LLM.

Flow:
  1. Generate N hypotheses in parallel (each with a distinct system prompt)
  2. Judge evaluates all hypotheses against the query + context
  3. Return the best hypothesis (or merge-able metadata)
"""

import asyncio
import logging
from typing import List, Dict, Optional

from app.services.generation import chat as llm_chat

logger = logging.getLogger(__name__)

# ── Perspective prompts ─────────────────────────────────────────────

HYPOTHESIS_PROMPTS = {
    "conservative": (
        "你是一个严格引用型回答助手。"
        "你的核心原则：只说文档中明确写明的信息，绝不进行推论或联想。"
        "如果文档没有直接答案，明确说'文档未明确说明'。"
        "引用时标注来源文档名。回答简洁、准确、保守。"
    ),
    "analytical": (
        "你是一个综合分析型回答助手。"
        "你会阅读所有提供的文档片段，找出跨文档的共性、差异和递进关系。"
        "在文档内容的基础上做合理推断（但标注哪些是推断、哪些是原文）。"
        "适合需要综合多个来源才能回答的复杂问题。"
        "引用时标注来源文档名。回答条理清晰、有分析深度。"
    ),
    "structured": (
        "你是一个结构清晰型回答助手。"
        "你擅长把复杂信息组织成层次分明的回答——用标题、列表、分类来呈现。"
        "每个要点都有文档来源支撑。"
        "如果问题包含多个子问题，逐一回答。"
        "引用时标注来源文档名。回答结构清晰、便于阅读。"
    ),
}

HYPOTHESIS_PERSPECTIVES: List[str] = ["conservative", "analytical", "structured"]

# ── Judge prompt ────────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """你是一个答案质量评审专家。你的任务是评估多个候选答案的质量，选出最佳答案。

评估维度（每项1-10分）：
1. **准确性** — 答案内容是否忠实于提供的文档，不编造、不曲解
2. **完整性** — 答案是否覆盖了用户问题的所有方面（含多个子问题的情况）
3. **可读性** — 答案是否结构清晰、语言流畅、易于理解
4. **引用质量** — 是否准确标注信息来源

输出格式（JSON，不要其他内容）：
{
  "scores": [{"perspective": "conservative", "accuracy": 8, "completeness": 7, "readability": 6, "citations": 9, "total": 30}, ...],
  "best": "conservative",
  "reasoning": "简要说明为什么选这个"
}
"""


# ═══════════════════════════════════════════════════════════════════
# Core functions
# ═══════════════════════════════════════════════════════════════════


def _build_hypothesis_prompt(
    perspective: str,
    query: str,
    context: str,
    bank_prompt: str,
    history_context: str = "",
    _tier_hint: str = "",
) -> List[Dict]:
    """Build the messages list for a single hypothesis generation call."""
    perspective_prompt = HYPOTHESIS_PROMPTS.get(
        perspective, HYPOTHESIS_PROMPTS["analytical"]
    )

    system_prompt = f"{bank_prompt}\n\n{perspective_prompt}"

    user_prompt = f"""请按以下文档内容回答问题。

文档内容：
{context}
{history_context}

问题：{query}

请用中文回答，引用具体条款和数据，并标注信息来源。"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _generate_hypothesis(
    perspective: str,
    query: str,
    context: str,
    bank_prompt: str,
    history_context: str = "",
    _tier_hint: str = "",
    temperature: float = 0.3,
) -> Dict:
    """Generate a single hypothesis answer from one perspective.

    Returns:
        {"perspective": str, "answer": str}
    """
    messages = _build_hypothesis_prompt(
        perspective, query, context, bank_prompt, history_context, _tier_hint
    )

    # Slightly different temperatures per perspective for diversity
    temp_map = {"conservative": 0.1, "analytical": 0.4, "structured": 0.3}
    temp = temp_map.get(perspective, temperature)

    try:
        answer = await llm_chat(messages, temperature=temp)
        return {"perspective": perspective, "answer": answer}
    except Exception as e:
        logger.warning("Hypothesis '%s' failed: %s", perspective, e)
        return {"perspective": perspective, "answer": f"（{perspective} 视角生成失败: {e}）"}


async def _judge_hypotheses(
    query: str,
    context: str,
    hypotheses: List[Dict],
) -> Dict:
    """Evaluate all hypotheses and select the best one.

    Returns:
        {"best_perspective": str, "best_answer": str, "all_scores": [...], "reasoning": str}
    """
    # Build the judge comparison content
    hypotheses_text = "\n\n---\n\n".join(
        f"## {h['perspective'].upper()} 视角\n\n{h['answer']}"
        for h in hypotheses
    )

    judge_user_prompt = f"""用户问题: {query}

参考文档:
{context[:6000]}

候选答案:
{hypotheses_text}

请按评审标准评估，选出最佳答案。输出JSON格式。"""

    try:
        judge_result = await llm_chat(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": judge_user_prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )

        # Parse JSON from judge result
        import json

        # Extract JSON from the response (it may be wrapped in markdown)
        cleaned = judge_result.strip()
        for marker in ["```json", "```"]:
            if marker in cleaned:
                cleaned = cleaned.replace(marker, "")
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON object boundaries
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None
            else:
                parsed = None

        if parsed and isinstance(parsed, dict):
            best_perspective = parsed.get("best", hypotheses[0]["perspective"])
            best_answer = None
            for h in hypotheses:
                if h["perspective"] == best_perspective:
                    best_answer = h["answer"]
                    break
            if not best_answer:
                best_answer = hypotheses[0]["answer"]
                best_perspective = hypotheses[0]["perspective"]

            return {
                "best_perspective": best_perspective,
                "best_answer": best_answer,
                "all_scores": parsed.get("scores", []),
                "reasoning": parsed.get("reasoning", ""),
            }
    except Exception as e:
        logger.warning("Judge evaluation failed: %s", e)

    # Fallback: return the analytical hypothesis (most balanced)
    fallback = next(
        (h for h in hypotheses if h["perspective"] == "analytical"),
        hypotheses[0],
    )
    return {
        "best_perspective": fallback["perspective"],
        "best_answer": fallback["answer"],
        "all_scores": [],
        "reasoning": "Judge fallback (evaluation failed)",
    }


async def multi_hypothesis_answer(
    query: str,
    context: str,
    bank_prompt: str,
    history_context: str = "",
    _tier_hint: str = "",
    perspectives: Optional[List[str]] = None,
) -> Dict:
    """Generate answer using multi-hypothesis comparison.

    Args:
        query: User's query
        context: Retrieved document context
        bank_prompt: System prompt for the bank
        history_context: Chat history context
        _tier_hint: Tier hint string
        perspectives: List of perspectives to use (default: all 3)

    Returns:
        {
            "answer": str,           # The selected best answer
            "multi_hypothesis": {     # Metadata
                "hypotheses": [{perspective, answer}, ...],
                "best_perspective": str,
                "scores": [...],
                "reasoning": str,
            }
        }
    """
    if perspectives is None:
        perspectives = HYPOTHESIS_PERSPECTIVES

    # Step 1: Generate all hypotheses in parallel
    tasks = [
        _generate_hypothesis(p, query, context, bank_prompt, history_context, _tier_hint)
        for p in perspectives
    ]
    hypotheses = await asyncio.gather(*tasks)

    # Step 2: Judge and select
    judge_result = await _judge_hypotheses(query, context, hypotheses)

    return {
        "answer": judge_result["best_answer"],
        "multi_hypothesis": {
            "hypotheses": hypotheses,
            "best_perspective": judge_result["best_perspective"],
            "scores": judge_result["all_scores"],
            "reasoning": judge_result["reasoning"],
        },
    }
