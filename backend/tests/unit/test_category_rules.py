"""回归锁：XHS bank 的 category 映射不得落入隔离类（ISOLATED_CATEGORIES）。

背景（2026-10-04/05）：
 ① `BANK_TO_CATEGORY["kb_xhs"]` 曾为 `"daily"`，而 `daily/news ∈ ISOLATED_CATEGORIES`
    ⇒ `query_engine` 的 Category 过滤在 `categories` 参数≠`all`（默认空串）时
    剔除隔离类 ⇒ 用 `bank=kb_xhs` 上传的 XHS 笔记**默认检索不到**。
 ② 更深一层：`infer_category` 的**标题正则优先于 bank 映射**，且兜底正则
    `(日常|笔记|草稿|memo|note|README)→daily`、`(新闻|资讯|动态|周报|月报|趋势)→news`
    会把标题含这些词的 XHS 文档拉回隔离类（实证：`MeMo:...` → daily；
    `本周AI动态` → news）。故新增「bank 非隔离映射 > 隔离兜底正则」守卫。

本文件钉死：① 映射值 ② infer_category 行为产出 ③ 双键一致 ④ 守卫不过度抑制。
"""
import pytest

from app.services.category_rules import (
    BANK_TO_CATEGORY,
    ISOLATED_CATEGORIES,
    infer_category,
)


# ── ① 映射常量 ────────────────────────────────────────────────
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


# ── ② 行为产出（无关键词标题 → 走 bank 映射）────────────────────
@pytest.mark.parametrize("bank", ["kb_xhs", "咨询"])
def test_infer_category_never_isolated_for_xhs_bank(bank):
    cat = infer_category(title="xhs_aoci_code", filename="xhs_aoci_code.md", bank=bank)
    assert cat not in ISOLATED_CATEGORIES, (
        f"infer_category(bank={bank!r}) 产出隔离类 {cat!r} ⇒ 默认检索不可见（回归）"
    )


# ── ③ 守卫：标题含隔离兜底关键词也不得落隔离类 ────────────────
@pytest.mark.parametrize("bank", ["kb_xhs", "咨询"])
@pytest.mark.parametrize("title,note", [
    ("MeMo:解决大规模知识库问答的新思路", "命中 memo→daily"),
    ("我的学习笔记-某工具",              "命中 笔记→daily"),
    ("本周AI行业动态速览",               "命中 动态→news"),
    ("AI资讯速递",                       "命中 资讯→news"),
])
def test_isolated_title_keyword_cannot_hijack_xhs_bank(bank, title, note):
    cat = infer_category(title=title, bank=bank)
    assert cat not in ISOLATED_CATEGORIES, (
        f"bank={bank!r} + title={title!r}（{note}）产出隔离类 {cat!r} ⇒ 守卫失效（回归）"
    )


# ── ④ 守卫不得过度抑制：非隔离类正则仍应正常命中 ──────────────
def test_guard_does_not_suppress_non_isolated_regex():
    """等保/测评 等非隔离正则命中时，仍按正则走（不被 bank 映射顶掉）。"""
    assert infer_category(title="等保测评笔记", bank="kb_xhs") == "security"
    # 造价类（非隔离）应正常命中；标准类用显式标准号
    assert infer_category(title="工程造价取费定额", bank="kb_xhs") == "cost"
    assert infer_category(title="GB/T 28181 安全防范标准", bank="kb_xhs") == "standard"


# ── ⑤ 无 bank 上下文时行为不变（回归：不得误伤通用调用）─────────
@pytest.mark.parametrize("title,expected", [
    ("本周AI行业动态速览", "news"),
    ("我的日常记录",       "daily"),
])
def test_no_bank_context_behavior_unchanged(title, expected):
    assert infer_category(title=title) == expected, (
        "无 bank 上下文时，隔离类正则行为必须不变（否则误伤通用上传路径）"
    )
