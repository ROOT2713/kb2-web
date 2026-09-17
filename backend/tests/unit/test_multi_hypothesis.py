#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多假设对比接线回归锁（出处: R5 交付包 P0-2 / 本仓批次 A）

背景：前端 `services/query.ts:78` 一直在发 `multi_hypothesis=true`，但后端
`query()` 签名未声明 → FastAPI 静默忽略 → `multi_hypothesis_answer()` 零调用方，
功能从未生效。本文件锁定接线后的 4 类行为，防回退。

patch 目标判定（遵循 harness-templates 的 mock 规则）：
  · `chat` 在 query_engine **模块顶** import → patch 消费模块 `app.api.query_engine.chat`
  · `multi_hypothesis_answer` 在 `_generate_answer` **函数体内** lazy import
    → patch 源模块 `app.services.multi_hypothesis.multi_hypothesis_answer`
"""
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from app.api.query_engine import _generate_answer
from app.services import multi_hypothesis as mh

_BACKEND = pathlib.Path(__file__).resolve().parents[2]
_QUERY_PY = _BACKEND / "app" / "api" / "query.py"
_ENGINE_PY = _BACKEND / "app" / "api" / "query_engine.py"


# ── 夹具 ────────────────────────────────────────────────────────
def _doc_facts():
    """单文档、pidx=None → 不触发 parent_chunks 查询，隔离 DB。"""
    return {"doc-a": [("chunk text 内容", "示例文档A", "示例文档A 的正文内容片段", None)]}


async def _call_engine(multi: bool, fake_chat=None):
    """以最小参数调用 _generate_answer；chat 用假实现避免真实 LLM。"""
    fake_chat = fake_chat or AsyncMock(return_value="单路答案内容" * 20)
    with patch("app.api.query_engine.chat", fake_chat):
        return await _generate_answer(
            q="测试问题",
            bank="general",
            bank_prompt="BANK_PROMPT",
            history="",
            doc_facts=_doc_facts(),
            query_keywords=["测试"],
            _tier_extra=[],
            title_map={"doc-a": "示例文档A"},
            kg_context_text="",
            ctx={"comparison_hint": ""},
            multi_hypothesis=multi,
        )


# ══════════════════════════════════════════════════════════════════
# 1. _generate_answer 分支行为
# ══════════════════════════════════════════════════════════════════
class TestGenerateAnswerBranch:
    @pytest.mark.asyncio
    async def test_multi_on_uses_multi_hypothesis_answer(self):
        """开启时走多假设，且单路 chat 不再被调用（不白烧一次 LLM）。"""
        fake_mh = AsyncMock(return_value={
            "answer": "多假设择优答案",
            "multi_hypothesis": {
                "hypotheses": [{"perspective": "analytical", "answer": "x"}],
                "best_perspective": "analytical",
                "scores": [],
                "reasoning": "更完整",
            },
        })
        single = AsyncMock(return_value="单路答案不应被用到")
        with patch("app.services.multi_hypothesis.multi_hypothesis_answer", fake_mh):
            out = await _call_engine(True, fake_chat=single)

        assert out["answer"] == "多假设择优答案"
        assert out["multi_hypothesis"]["best_perspective"] == "analytical"
        assert single.await_count == 0, "开启多假设时不应再调用单路 chat"

    @pytest.mark.asyncio
    async def test_multi_off_does_not_call_multi_hypothesis(self):
        """未开启时行为完全不变：不调用多假设，元数据为 None。"""
        fake_mh = AsyncMock()
        with patch("app.services.multi_hypothesis.multi_hypothesis_answer", fake_mh):
            out = await _call_engine(False)

        assert out["answer"] == "单路答案内容" * 20
        assert out["multi_hypothesis"] is None
        assert fake_mh.await_count == 0

    @pytest.mark.asyncio
    async def test_multi_failure_falls_back_to_single(self):
        """多假设抛异常 → 回落单路生成，主链路不中断、元数据为 None。"""
        fake_mh = AsyncMock(side_effect=RuntimeError("模拟多假设故障"))
        with patch("app.services.multi_hypothesis.multi_hypothesis_answer", fake_mh):
            out = await _call_engine(True)

        assert out["answer"] == "单路答案内容" * 20, "失败后必须回落单路"
        assert out["multi_hypothesis"] is None

    @pytest.mark.asyncio
    async def test_return_contract_keeps_degraded_and_kg_context(self):
        """R5 包内补丁的返回值漏掉了 kg_context_text / degraded —— 会静默回退 R3-1 降级拦截。

        本用例锁死：返回结构必须同时含这两键（缺任一即回归）。
        """
        out = await _call_engine(False)
        assert "degraded" in out, "丢失 degraded 会让降级文本被缓存 24h（R3-1 回退）"
        assert "kg_context_text" in out
        assert out["degraded"] is False

    @pytest.mark.asyncio
    async def test_multi_hypothesis_receives_main_prompt(self):
        """多假设必须拿到主链路完整 prompt（费率/对比/字数规则），而非模块内简版 prompt。"""
        fake_mh = AsyncMock(return_value={"answer": "A", "multi_hypothesis": None})
        with patch("app.services.multi_hypothesis.multi_hypothesis_answer", fake_mh):
            await _call_engine(True)

        assert fake_mh.await_count == 1
        kw = fake_mh.await_args.kwargs
        assert kw["query"] == "测试问题"
        assert kw["bank_prompt"] == "BANK_PROMPT"
        assert "user_prompt" in kw and kw["user_prompt"], "必须透传主链路 prompt"
        assert "安全约束" in kw["user_prompt"], "主链路 prompt 的安全约束段应存在"


# ══════════════════════════════════════════════════════════════════
# 2. multi_hypothesis.py 的 user_prompt 支持
# ══════════════════════════════════════════════════════════════════
class TestHypothesisPromptReuse:
    @pytest.mark.asyncio
    async def test_user_prompt_replaces_simple_prompt_keeps_perspective(self):
        """user_prompt 生效时：user 段=主链路 prompt，system 段仍带视角差异。"""
        captured = {}

        async def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return "hypo answer"

        with patch.object(mh, "llm_chat", fake_chat):
            await mh._generate_hypothesis(
                "conservative", "Q", "CTX", "BANK", user_prompt="FULL_MAIN_PROMPT"
            )

        msgs = captured["messages"]
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "FULL_MAIN_PROMPT", "应使用主链路 prompt"
        assert "请按以下文档内容回答问题" not in msgs[1]["content"], "不应残留模块简版 prompt"
        assert msgs[0]["role"] == "system"
        assert "BANK" in msgs[0]["content"]
        assert mh.HYPOTHESIS_PROMPTS["conservative"] in msgs[0]["content"], "视角差异须保留"

    @pytest.mark.asyncio
    async def test_without_user_prompt_keeps_legacy_behavior(self):
        """不传 user_prompt 时保持原行为（向后兼容）。"""
        captured = {}

        async def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return "hypo answer"

        with patch.object(mh, "llm_chat", fake_chat):
            await mh._generate_hypothesis("analytical", "Q", "CTX", "BANK")

        assert "请按以下文档内容回答问题" in captured["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_multi_hypothesis_answer_propagates_user_prompt(self):
        """3 个视角的生成调用都必须带上同一个 user_prompt。"""
        seen = []

        async def fake_gen(perspective, query, context, bank_prompt,
                           history_context="", _tier_hint="", user_prompt=None):
            seen.append((perspective, user_prompt))
            return {"perspective": perspective, "answer": f"ans-{perspective}"}

        async def fake_judge(query, context, hypotheses):
            return {"best_perspective": "conservative", "best_answer": "best",
                    "all_scores": [], "reasoning": ""}

        with patch.object(mh, "_generate_hypothesis", fake_gen), \
             patch.object(mh, "_judge_hypotheses", fake_judge):
            out = await mh.multi_hypothesis_answer(
                query="Q", context="CTX", bank_prompt="BANK", user_prompt="FULL"
            )

        assert len(seen) == 3
        assert all(up == "FULL" for _, up in seen), "三个视角都须收到主链路 prompt"
        assert out["answer"] == "best"
        assert len(out["multi_hypothesis"]["hypotheses"]) == 3


# ══════════════════════════════════════════════════════════════════
# 3. API 接线源码级回归锁（防再次「前端发、后端无此形参」）
# ══════════════════════════════════════════════════════════════════
class TestApiWiringLocks:
    def test_query_declares_multi_hypothesis_form_param(self):
        src = _QUERY_PY.read_text(encoding="utf-8")
        assert 'multi_hypothesis: str = Form(' in src, \
            "query() 必须声明 multi_hypothesis 形参，否则 FastAPI 再次静默忽略"
        assert '_use_multi_hypothesis' not in src or 'use_multi_hypothesis' in src

    def test_cache_scope_isolates_multi_hypothesis(self):
        """多假设产出与单路产出语义不同 → 必须进缓存隔离维度（防互相串答案）。"""
        src = _QUERY_PY.read_text(encoding="utf-8")
        assert "mh={int(use_multi_hypothesis)}" in src, \
            "cache_scope 必须含 mh= 维度，否则勾选/未勾选会互吃缓存"

    def test_engine_return_does_not_drop_degraded(self):
        """R5 包内 snippet 的返回值漏了 degraded/kg_context_text —— 锁死防照抄。"""
        src = _ENGINE_PY.read_text(encoding="utf-8")
        idx = src.index('"multi_hypothesis": _mh_meta')
        window = src[max(0, idx - 500):idx]
        assert '"degraded": degraded' in window, "multi_hypothesis 返回值邻近处必须保留 degraded"
        assert '"kg_context_text": kg_context_text' in window
