"""批次 B 接线测试：answer_structurer 的消费点（`_structure_telemetry`）。

背景
----
R5 交付包只给了 `answer_structurer.py`（331 行纯函数）本身，**不给调用方** ——
「落地≠生效」。本仓库在 `app/api/query_engine.py` 接了两处：

  ① `_fee_rules` 末尾追加 `prompt_hardening.build_fee_hint()`
     （防回退锁见 test_prompt_hardening.py § D）
  ② `_generate_answer()` 返回前调 `_structure_telemetry(answer)`，把回答过一遍
     结构解析，出现「坏表」修复标记时记一行 `[STRUCTURE]` 日志

本文件覆盖 ②：既有纯函数断言（带牙齿），也有一条真实调用链断言
（patch 掉 LLM，让 `_generate_answer` 真跑一遍，验证日志确实被触发）。
"""

import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from app.api.query_engine import _generate_answer, _structure_telemetry
from app.services import answer_structurer as ast

# 真实坏表：表头 5 列，分隔行只敲了 3 格（截图里线上出现过的形态）
BAD_TABLE_ANSWER = (
    "| 地市/标准 | 费用类型 | 金额（万元） | 计算公式 | 依据文件及表号 |\n"
    "|---|----|----|\n"
    "| 省级 | 验收测评费 | 15.00 | V=D×g×(1-Z) | 《电子政务工程造价指导书》表5-49 |\n"
    "| 东莞市 | 验收测评费 | 9.60 | V=8+(500-400)×1.6% | 《东莞市政府投资信息化项目造价指南》表9 |\n"
)

# 照抄硬模板产出的好表（与 test_prompt_hardening.py § C 同源）
GOOD_TABLE_ANSWER = (
    "先给出结论：省级 15.00 万元，东莞市 9.60 万元。\n\n"
    "| 地市/标准 | 费用类型 | 金额（万元） | 计算公式 | 依据文件及表号 |\n"
    "|---|---|---|---|---|\n"
    "| 省级 | 验收测评费 | 15.00 | V=D×g×(1-Z) | 表5-49 |\n"
    "| 东莞市 | 验收测评费 | 9.60 | V=8+(500-400)×1.6% | 表9 |\n"
)


# ═══════════════════════════════════════════════════════════════════
# 1. 纯函数：坏表必须被标记 / 好表零标记
# ═══════════════════════════════════════════════════════════════════
def test_bad_table_is_flagged():
    st = _structure_telemetry(BAD_TABLE_ANSWER)
    assert st["table"] == 1
    assert st["repaired"] == 1
    assert ast.FIX_SEPARATOR_COLUMN_MISMATCH in st["flags"]


def test_good_table_is_clean():
    st = _structure_telemetry(GOOD_TABLE_ANSWER)
    assert st["table"] == 1
    assert st["repaired"] == 0
    assert st["flags"] == []
    assert st["conclusion"] == 1  # 「先给出结论」被识别为结论块


def test_text_only_answer_has_no_flags():
    st = _structure_telemetry("这是一段没有任何表格的普通回答。" * 5)
    assert st["table"] == 0
    assert st["repaired"] == 0
    assert st["flags"] == []


def test_empty_and_non_string_input_degrade_safely():
    """空串 → 合法零值；非字符串 → 兜底 {}（绝不抛错拖垮主链路）。"""
    st_empty = _structure_telemetry("")
    assert st_empty["blocks"] == 0 and st_empty["repaired"] == 0
    assert _structure_telemetry(None)["repaired"] == 0
    assert _structure_telemetry(12345) == {}  # int 无 .strip() → 异常被吞


# ═══════════════════════════════════════════════════════════════════
# 2. 接线锁（防「函数写好了但没人调」）
# ═══════════════════════════════════════════════════════════════════
def _src() -> str:
    return (Path(__file__).resolve().parents[2] / "app" / "api" / "query_engine.py").read_text(encoding="utf-8")


def test_generate_answer_calls_telemetry():
    src = _src()
    assert "from app.services.answer_structurer import" in src
    assert "_st = _structure_telemetry(answer)" in src
    assert '"[STRUCTURE] repaired=%d/%d tables' in src
    # 必须在 return 之前
    assert src.index("_structure_telemetry(answer)") < src.index('"multi_hypothesis": _mh_meta')


def test_telemetry_is_defined_before_use():
    src = _src()
    assert src.index("def _structure_telemetry(answer: str) -> dict:") < src.index(
        "_st = _structure_telemetry(answer)"
    )


# ═══════════════════════════════════════════════════════════════════
# 3. 真实调用链：让 _generate_answer 跑一遍，日志必须被触发
# ═══════════════════════════════════════════════════════════════════
class _FakeChatRecorder:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list = []

    async def __call__(self, messages, temperature=0.1, max_tokens=8000, **kw):
        self.prompts.append(messages[-1]["content"])
        return self.reply


async def _run_generate(monkeypatch, reply: str, q: str):
    import app.api.query_engine as qe

    rec = _FakeChatRecorder(reply)
    monkeypatch.setattr(qe, "chat", rec)
    facts = {
        "d-wiring-001": [(
            "验收测评费率 2.0%",
            "《东莞市信息化项目造价指南》",
            "表9 验收测评费率 2.0%（速算增加额法）",
            None,
        )]
    }
    res = await qe._generate_answer(
        q=q, bank="all", bank_prompt="", history="", doc_facts=facts,
        query_keywords=[], _tier_extra=[], title_map={"d-wiring-001": "x"},
        kg_context_text="", ctx={},
    )
    return res, rec


@pytest.mark.asyncio
async def test_wiring_emits_structure_log_on_bad_table(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.query_engine"):
        res, rec = await _run_generate(
            monkeypatch, BAD_TABLE_ANSWER, "东莞市500万元项目的验收测评费是多少？"
        )
    assert rec.prompts, "LLM 未被调用，说明测试没走到生成阶段"
    assert "[STRUCTURE] repaired=" in caplog.text, caplog.text[-800:]


@pytest.mark.asyncio
async def test_wiring_injects_fee_template_into_fee_prompt(monkeypatch):
    """CC 建议 4：不靠源码子串锁，真跑一遍断言费用 prompt 含硬化片段（接线有牙齿）。"""
    from app.services.prompt_hardening import build_fee_hint

    hint = build_fee_hint()
    assert hint.strip(), "硬化片段为空，本测试失去意义"
    _res, rec = await _run_generate(
        monkeypatch, GOOD_TABLE_ANSWER, "东莞市500万元项目的验收测评费是多少？"
    )
    assert rec.prompts, "LLM 未被调用，说明测试没走到生成阶段"
    assert hint in rec.prompts[0], "费用查询 prompt 未注入硬化片段 —— 接线失效"


@pytest.mark.asyncio
async def test_wiring_skips_fee_template_for_non_fee_query(monkeypatch):
    """反向核验：非费用查询不得注入硬化片段（费用门控成立，避免污染通用回答）。"""
    from app.services.prompt_hardening import build_fee_hint

    hint = build_fee_hint()
    _res, rec = await _run_generate(
        monkeypatch, GOOD_TABLE_ANSWER, "知识库支持上传哪些文件格式？"
    )
    assert rec.prompts, "LLM 未被调用"
    assert hint not in rec.prompts[0], "非费用查询被注入了费用表格硬化片段"


@pytest.mark.asyncio
async def test_wiring_silent_on_clean_table(monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.query_engine"):
        await _run_generate(
            monkeypatch, GOOD_TABLE_ANSWER, "东莞市500万元项目的验收测评费是多少？"
        )
    assert "[STRUCTURE] repaired=" not in caplog.text
