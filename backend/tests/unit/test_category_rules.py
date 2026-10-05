"""回归锁：XHS bank 的 category 映射不得落入隔离类（ISOLATED_CATEGORIES）。

背景（2026-10-04）：`BANK_TO_CATEGORY["kb_xhs"]` 曾为 `"daily"`，而
`daily/news ∈ ISOLATED_CATEGORIES` ⇒ `query_engine` 的 Category 过滤在
`categories` 参数≠`all`（默认空串）时剔除隔离类 ⇒ 用 `bank=kb_xhs` 上传的
XHS 笔记**默认检索不到**（实证：AOCI-CODE 笔记三层验证第③层 0 命中）。

修复：`kb_xhs → consulting`，与 legacy `咨询` 键对齐。
本文件钉死：① 映射值本身 ② infer_category 的实际产出 ③ 双键一致性。
"""
import pytest

from app.services.category_rules import (
    BANK_TO_CATEGORY,
    ISOLATED_CATEGORIES,
    infer_category,
)


@pytest.mark.parametrize("bank", ["kb_xhs", "咨询"])
def test_xhs_bank_maps_to_non_isolated(bank):
    """XHS 两个 bank 键的映射值不得是隔离类。"""
    cat = BANK_TO_CATEGORY.get(bank)
    assert cat, f"BANK_TO_CATEGORY 缺少 {bank!r} 映射"
    assert cat not in ISOLATED_CATEGORIES, (
        f"{bank!r} 映射到隔离类 {cat!r} ⇒ 上传后默认检索被剔除（回归）"
    )


def test_kb_xhs_aligned_with_legacy_zixun():
    """kb_xhs（物理库名键）与 咨询（legacy 业务键）必须落到同一 category。"""
    assert BANK_TO_CATEGORY["kb_xhs"] == BANK_TO_CATEGORY["咨询"]


@pytest.mark.parametrize("bank", ["kb_xhs", "咨询"])
def test_infer_category_never_isolated_for_xhs_bank(bank):
    """行为断言（比读常量更有牙齿）：无标题关键词命中时，
    infer_category 走 bank 映射分支，产出不得是隔离类。"""
    cat = infer_category(title="xhs_aoci_code", filename="xhs_aoci_code.md", bank=bank)
    assert cat not in ISOLATED_CATEGORIES, (
        f"infer_category(bank={bank!r}) 产出隔离类 {cat!r} ⇒ 默认检索不可见（回归）"
    )
