"""answer_structurer 单元测试

可直接放入 backend/tests/unit/，也可独立运行：python -m pytest test_answer_structurer.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

try:
    from app.services.answer_structurer import (  # type: ignore
        structure_answer, structure_stats, has_own_numbering,
        KIND_CONCLUSION, KIND_TEXT, KIND_TABLE, KIND_NOTE,
        FIX_SEPARATOR_COLUMN_MISMATCH, FIX_NO_SEPARATOR,
    )
except Exception:  # pragma: no cover
    _HERE = pathlib.Path(__file__).resolve()
    _p = _HERE.parent / "answer_structurer.py"
    _spec = importlib.util.spec_from_file_location("_as_mod", _p)
    _m = importlib.util.module_from_spec(_spec)  # type: ignore
    sys.modules["_as_mod"] = _m
    _spec.loader.exec_module(_m)  # type: ignore
    structure_answer = _m.structure_answer
    structure_stats = _m.structure_stats
    has_own_numbering = _m.has_own_numbering
    KIND_CONCLUSION, KIND_TEXT = _m.KIND_CONCLUSION, _m.KIND_TEXT
    KIND_TABLE, KIND_NOTE = _m.KIND_TABLE, _m.KIND_NOTE
    FIX_SEPARATOR_COLUMN_MISMATCH = _m.FIX_SEPARATOR_COLUMN_MISMATCH
    FIX_NO_SEPARATOR = _m.FIX_NO_SEPARATOR


# 截图那道题的真实回答
REAL_BAD = """先给出结论枚举：① 验收测评费：东莞市 2.00 万元、佛山市 2.00 万元；② 等保测评费：仅佛山口径可查，\
二级非政务云 5.94 万元；③ 商密测评费：未检索到费率表。
| 地市/标准 | 费用类型 | 金额（万元） | 计算公式 | 依据文件及表号 |
|---|----|----|
| 省级 | 验收测评费率表未检索到 | — | — | 《电子政务工程造价指导书（2019年）》 |
| 东莞市 | 验收测评费 | 2.00 | V=0+100×2% | 《东莞市政府投资信息化项目造价指南（修编版）》表9 |
| 佛山市 | 等保测评费（三级、非政务云） | 6.93 | 同上档位 | 同上表 |

说明1：验收测评费与等保测评费是不同费用类型，不可混用。
说明2：项目主体实施费用即 100万元。
说明3：商密测评费用文档未覆盖。"""


# ══════════════════════════════════════════════════════════════════════
# 1. 截图复现
# ══════════════════════════════════════════════════════════════════════
def test_real_answer_block_sequence():
    blocks = structure_answer(REAL_BAD)
    kinds = [b["kind"] for b in blocks]
    assert kinds == [KIND_CONCLUSION, KIND_TABLE, KIND_NOTE, KIND_NOTE, KIND_NOTE]


def test_real_answer_table_columns_aligned():
    blocks = structure_answer(REAL_BAD)
    t = next(b for b in blocks if b["kind"] == KIND_TABLE)["table"]
    assert len(t["headers"]) == 5
    assert all(len(r) == 5 for r in t["rows"])
    assert len(t["rows"]) == 3


def test_real_answer_flags_separator_mismatch():
    blocks = structure_answer(REAL_BAD)
    t = next(b for b in blocks if b["kind"] == KIND_TABLE)["table"]
    assert FIX_SEPARATOR_COLUMN_MISMATCH in t["repair_flags"]
    assert t["repaired"] is True


def test_real_answer_note_split_into_three():
    blocks = structure_answer(REAL_BAD)
    notes = [b for b in blocks if b["kind"] == KIND_NOTE]
    assert len(notes) == 3
    assert notes[0]["index"] == 2 and notes[2]["index"] == 4


def test_real_answer_stats():
    st = structure_stats(structure_answer(REAL_BAD))
    assert st == {"conclusion": 1, "table": 1, "note": 3, "text": 0, "repaired": 1}


# ══════════════════════════════════════════════════════════════════════
# 2. 表格容错
# ══════════════════════════════════════════════════════════════════════
def test_missing_separator_repaired():
    md = "| A | B |\n| 1 | 2 |\n| 3 | 4 |"
    t = structure_answer(md)[0]["table"]
    assert FIX_NO_SEPARATOR in t["repair_flags"]
    assert len(t["rows"]) == 2


def test_fullwidth_pipe_normalized():
    md = "| 地市 ｜ 费用 |\n|---|---|\n| 东莞 ｜ 验收 |"
    blocks = structure_answer(md)
    assert blocks[0]["kind"] == KIND_TABLE


def test_row_with_extra_pipe_merged():
    md = "| A | B | C |\n|---|---|---|\n| x | y | 含 | 竖线 |"
    t = structure_answer(md)[0]["table"]
    assert all(len(r) == 3 for r in t["rows"])
    assert "竖线" in t["rows"][0][2]


def test_short_row_padded_with_dash():
    md = "| A | B | C |\n|---|---|---|\n| x | y |"
    t = structure_answer(md)[0]["table"]
    assert t["rows"][0] == ["x", "y", "—"]


# ══════════════════════════════════════════════════════════════════════
# 3. 编号
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("text", [
    "1. 验收测评费 2.00 万元",
    "1、第一条",
    "（1）第一条",
    "(2) 第二条",
    "【3】第三条",
    "1) 第四条",
])
def test_has_own_numbering_true(text):
    assert has_own_numbering(text) is True


@pytest.mark.parametrize("text", [
    "第一段普通正文。",
    "2019 年的数据表明费率稳定。",
    "说明1：不可混用。",
    "金额为 2.00 万元。",
])
def test_has_own_numbering_false(text):
    assert has_own_numbering(text) is False


def test_numbered_flag_on_block():
    blocks = structure_answer("1. 第一条内容\n2. 第二条内容")
    assert blocks[0]["numbered"] is True


def test_table_never_numbered():
    blocks = structure_answer("| A | B |\n|---|---|\n| 1 | 2 |")
    assert blocks[0]["kind"] == KIND_TABLE
    assert blocks[0]["numbered"] is False


# ══════════════════════════════════════════════════════════════════════
# 4. 来源引用
# ══════════════════════════════════════════════════════════════════════
def test_refs_extracted():
    blocks = structure_answer("根据费率表[1]与指导书[2]，结果为 2.00 万元[1]。")
    assert blocks[0]["refs"] == [1, 2]


def test_refs_chinese_brackets():
    assert structure_answer("依据【3】计算。")[0]["refs"] == [3]


def test_refs_year_not_matched():
    assert structure_answer("2019年的数据[2019]。")[0]["refs"] == []


# ══════════════════════════════════════════════════════════════════════
# 5. 降级与边界
# ══════════════════════════════════════════════════════════════════════
def test_empty_input():
    assert structure_answer("") == []
    assert structure_answer("   ") == []
    assert structure_answer(None) == []  # type: ignore[arg-type]


def test_plain_text_single_block():
    blocks = structure_answer("就是一段普通的话。")
    assert len(blocks) == 1 and blocks[0]["kind"] == KIND_TEXT


def test_single_pipe_line_not_table():
    blocks = structure_answer("a | b | c 这样的行不应成表。")
    assert all(b["kind"] != KIND_TABLE for b in blocks)


def test_json_serializable():
    import json
    s = json.dumps(structure_answer(REAL_BAD), ensure_ascii=False)
    assert "separator_column_mismatch" in s


def test_no_content_loss():
    blocks = structure_answer(REAL_BAD)
    t = next(b for b in blocks if b["kind"] == KIND_TABLE)["table"]
    cells = [c for r in t["rows"] for c in r]
    assert "东莞市" in cells and "2.00" in cells and "6.93" in cells
    assert all(c for c in cells)
