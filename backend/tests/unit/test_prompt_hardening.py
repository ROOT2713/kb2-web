"""prompt_hardening 单测

覆盖三类断言：
  A. 模板本身合法（列数、管道符数、空行规则）—— 模板自己歪掉就全盘皆输；
  B. 自检条款可执行（必须含"逐条数管道符"这类可动作指令）；
  C. 与 answer_structurer 的闭环（用模板产出的表格必须零修复标记）。

代码基线：main `b0a9dff`
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_M_HARD = None
_M_STRUCT = None


def _load(name: str, filename: str):
    """优先按仓库布局从 `app.services` 导入，交付包布局（与本测试同目录）作为兜底。

    交付包原始版本只认同目录文件；落到 backend/tests/unit/ 后模块在
    backend/app/services/，故此处加一层导入优先，行为与交付包一致（同一份源码）。
    """
    try:
        return importlib.import_module(f"app.services.{Path(filename).stem}")
    except Exception:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / filename)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def _mods():
    global _M_HARD, _M_STRUCT
    if _M_HARD is None:
        _M_HARD = _load("prompt_hardening_under_test", "prompt_hardening.py")
        _M_STRUCT = _load("answer_structurer_under_test", "answer_structurer.py")
    return _M_HARD, _M_STRUCT


def _cells(line: str) -> list:
    t = line.strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|"):
        t = t[:-1]
    return [c.strip() for c in t.split("|")]


# ══════════════════════════════════════════════════════════════════════
# A. 模板本身合法
# ══════════════════════════════════════════════════════════════════════
def test_template_has_five_columns():
    hard, _ = _mods()
    lines = [ln for ln in hard.FEE_TABLE_TEMPLATE.split("\n") if ln.strip()]
    for ln in lines:
        assert len(_cells(ln)) == 5, f"列数不是 5：{ln}"


def test_template_separator_matches_header():
    """这正是线上坏掉的那一行：分隔行列数必须等于表头列数。"""
    hard, _ = _mods()
    lines = [ln for ln in hard.FEE_TABLE_TEMPLATE.split("\n") if ln.strip()]
    assert len(_cells(lines[1])) == len(_cells(lines[0]))


def test_template_separator_pipe_count():
    hard, _ = _mods()
    sep = hard.FEE_TABLE_TEMPLATE.split("\n")[1].strip()
    assert sep.count("|") == 6
    assert len(re.findall(r"-{3}", sep)) == 5
    assert sep == "|---|---|---|---|---|"


def test_template_header_matches_constant():
    hard, _ = _mods()
    first = hard.FEE_TABLE_TEMPLATE.split("\n")[0]
    assert _cells(first) == hard.FEE_TABLE_HEADERS


def test_template_has_no_leading_trailing_blank():
    """模板不带首尾空行，拼进 prompt 后由调用方控制空行。"""
    hard, _ = _mods()
    assert not hard.FEE_TABLE_TEMPLATE.startswith("\n")
    assert not hard.FEE_TABLE_TEMPLATE.endswith("\n")


# ══════════════════════════════════════════════════════════════════════
# B. 自检条款可执行
# ══════════════════════════════════════════════════════════════════════
def test_self_check_mentions_pipe_count():
    hard, _ = _mods()
    assert "管道符" in hard.FEE_TABLE_SELF_CHECK


def test_self_check_mentions_separator_literal():
    hard, _ = _mods()
    assert "|---|---|---|---|---|" in hard.FEE_TABLE_SELF_CHECK


def test_self_check_has_list_fallback():
    """必须有出口：宁可列表也不要歪表。"""
    hard, _ = _mods()
    assert "无序列表" in hard.FEE_TABLE_SELF_CHECK
    assert "不要输出一张列数不齐的表格" in hard.FEE_TABLE_SELF_CHECK


def test_self_check_references_repair_flag():
    """与后端质量指标闭环：让 prompt 知道这个标记的存在。"""
    hard, _ = _mods()
    assert "separator_column_mismatch" in hard.FEE_TABLE_SELF_CHECK


def test_self_check_has_blank_line_rule():
    hard, _ = _mods()
    assert "空行" in hard.FEE_TABLE_SELF_CHECK


# ══════════════════════════════════════════════════════════════════════
# C. 与 answer_structurer 的闭环
# ══════════════════════════════════════════════════════════════════════
def _fill_template(hard, rows: list) -> str:
    """用模板产出一张填好数据的表，模拟 LLM 照抄后的结果。"""
    head = "\n".join(hard.FEE_TABLE_TEMPLATE.split("\n")[:2])
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return head + "\n" + body


def test_template_output_passes_structurer_clean():
    """照抄模板产出的表格，结构器必须给出零修复标记。"""
    hard, struct = _mods()
    text = _fill_template(hard, [
        ["省级", "验收测评费", "15.00", "V=D×g×(1-Z)", "《电子政务工程造价指导书》表5-49"],
        ["东莞市", "验收测评费", "2.00", "V=0+100×2%", "《东莞市政府投资信息化项目造价指南》表9"],
    ])
    blocks = struct.structure_answer(text)
    tables = [b for b in blocks if b["kind"] == struct.KIND_TABLE]
    assert len(tables) == 1
    assert tables[0]["table"]["repair_flags"] == []
    assert tables[0]["table"]["repaired"] is False
    assert len(tables[0]["table"]["headers"]) == 5
    assert len(tables[0]["table"]["rows"]) == 2


def test_self_check_would_have_caught_real_bug():
    """回归锚点：截图里真实坏掉的分隔行，结构器必须标记为 mismatch。"""
    hard, struct = _mods()
    bad = (
        "| 地市/标准 | 费用类型 | 金额（万元） | 计算公式 | 依据文件及表号 |\n"
        "|---|----|----|\n"
        "| 省级 | 验收测评费率表未检索到 | — | — | 《电子政务工程造价指导书（2019年）》 |"
    )
    blocks = struct.structure_answer(bad)
    table = next(b for b in blocks if b["kind"] == struct.KIND_TABLE)["table"]
    assert struct.FIX_SEPARATOR_COLUMN_MISMATCH in table["repair_flags"]
    # 修复后仍保持 5 列、数据不丢
    assert len(table["headers"]) == 5
    assert all(len(r) == 5 for r in table["rows"])


def test_hardening_block_is_appendable():
    """硬化片段必须是纯追加文本，不含替换型指令。"""
    hard, _ = _mods()
    txt = hard.build_fee_hint()
    assert txt.startswith("   l. ")
    assert hard.FEE_TABLE_TEMPLATE in txt
    assert "逐字符照抄" in txt
    for banned in ("替换上文", "删除上", "覆盖以上全部"):
        assert banned not in txt


def test_output_req_patch_uses_same_template():
    """【输出要求】#2 的补丁必须复用同一模板，避免两处漂移。"""
    hard, _ = _mods()
    assert hard.FEE_TABLE_TEMPLATE in hard.OUTPUT_REQ_2_PATCH
    assert "≥3 项" in hard.OUTPUT_REQ_2_PATCH


def test_table_self_check_detail_shares_source():
    hard, _ = _mods()
    assert hard.table_self_check_detail() == hard.FEE_TABLE_SELF_CHECK


# ══════════════════════════════════════════════════════════════════════
# D. 接线锁（批次 B 落地时新增）—— 防「模块落地了但没人消费」
#
# 交付包本身不含接线（它只给模块）；本仓库在 app/api/query_engine.py 的
# `_fee_rules` 拼装末尾追加上该片段。这里做的是**防回退锁**：任何删掉接线
# 的改动立即变红。运行时生效验证（重启后 journalctl [FEE_RULES] + 真实
# 费用查询答案含 5 列硬模板表）在部署步骤完成，不在此测试覆盖范围。
# ══════════════════════════════════════════════════════════════════════
def _query_engine_src() -> str:
    p = Path(__file__).resolve().parents[2] / "app" / "api" / "query_engine.py"
    return p.read_text(encoding="utf-8")


def test_query_engine_imports_build_fee_hint():
    src = _query_engine_src()
    assert "from app.services.prompt_hardening import build_fee_hint" in src


def test_fee_rules_block_consumes_hardening():
    """`+ _build_fee_table_hint()` 必须落在 `_fee_rules = (` 与 [FEE_RULES] 日志之间。"""
    src = _query_engine_src()
    start = src.index("_fee_rules = (")
    end = src.index("[FEE_RULES] Injected fee calculation rules", start)
    block = src[start:end]
    assert "+ _build_fee_table_hint()" in block
    assert block.count("_build_fee_table_hint()") == 1


def test_hardening_is_appended_not_replacing():
    """追加语义：既有末条规则（禁止跳过省级框架）必须仍在硬化片段之前。"""
    hard, _ = _mods()
    src = _query_engine_src()
    assert "也禁止跳过省级框架直接用地市数据" in src
    assert src.index("也禁止跳过省级框架直接用地市数据") < src.index("+ _build_fee_table_hint()")
    txt = hard.build_fee_hint()
    assert txt.startswith("   l. ")
    assert "也禁止跳过省级框架" not in txt

