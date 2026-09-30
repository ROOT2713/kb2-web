"""citation_check 单元测试（纯函数，零 IO / 零 LLM）。

两类断言：
  · **行为**：编造引用被拦、真实引用放行、空集/无引用不误拦；
  · **回归锚**：R7 自称修掉的两处缺陷（内层括号零提取、顿号粘连）各一条，
    回退即红；另加一条**形态边界**锚（【】默认关闭、正文不误判）。
"""
from __future__ import annotations

from app.services.citation_check import _normalize, check_citations

KNOWN = [
    "广东省省级政务信息化验收测评服务项目管理指引（试行）",
    "GB/T 39786-2021 解读",
]


# ── ① 基础行为 ───────────────────────────────────────────────
def test_book_title_citation_ok():
    ans = "根据《广东省省级政务信息化验收测评服务项目管理指引（试行）》第 3 条……"
    rep = check_citations(ans, KNOWN)
    assert rep.ok and rep.cited, "cited 必须非空（防空洞通过）"


def test_forged_source_rejected():
    rep = check_citations("根据《某不存在的白皮书》规定……", KNOWN)
    assert not rep.ok
    assert any("某不存在" in u for u in rep.unknown)


def test_source_prefix_citation_ok():
    rep = check_citations("来源：GB/T 39786-2021 解读", KNOWN)
    assert rep.ok and rep.cited


def test_no_citation_is_ok():
    """兜底型回答没有来源段 ⇒ 不判失败。"""
    assert check_citations("文档未明确说明。", KNOWN).ok


def test_empty_answer_ok():
    assert check_citations("", KNOWN).ok


def test_empty_known_skips():
    """检索为空 ⇒ skipped，不拦截（否则兜底答案会被误标 degraded）。"""
    rep = check_citations("根据《某指引》……", [])
    assert rep.ok and rep.skipped


# ── ② ★ R7 修正回归锚 ──────────────────────────────────────
def test_paren_file_with_inner_parens_extracted():
    """含内层括号的文件名必须真被提取（R7 原字符类 [^（）()] 会零提取）。"""
    ans = "（/uploads/广东省省级政务信息化验收测评服务项目管理指引（试行）.pdf）"
    rep = check_citations(ans, KNOWN)
    assert rep.cited, "必须真正提取到引用，而非空集假绿"
    assert rep.ok, f"归一化后应命中已知集，实得 unknown={rep.unknown}"


def test_source_with_enumeration_no_bleed():
    """`来源：A、B 两份` 的顿号不得把后续正文吞进引用串。"""
    ans = "来源：GB/T 39786-2021 解读、另有三份文档也提到了这一点"
    rep = check_citations(ans, KNOWN)
    assert rep.cited
    assert all("三份文档" not in c for c in rep.cited), "正文不得被吞入引用串"


def test_bracket_default_off():
    """【】形态默认关闭 —— 「【重要提示】」不得触发校验。"""
    rep = check_citations("【重要提示】本回答仅供参考。", KNOWN)
    assert rep.ok and not rep.cited
    rep2 = check_citations("【重要提示】本回答仅供参考。", KNOWN, enable_bracket=True)
    assert rep2.cited, "enable_bracket=True 时应启用"


def test_normalize_strips_path_and_ext():
    assert _normalize("/uploads/foo/bar.pdf") == "bar"
    assert _normalize("  某 文档 .MD ") == "某文档"


# ── ③ 已知误报面（特征化锚：行为变化必须显式改这条）───────────────
def test_known_false_positive_law_citation():
    """★ 如实登记已知误报面：法条/常识转引会被判 unknown。

    这不是本模块的 bug，而是「形态级校验」的固有边界。**接线前**必须
    用真实语料回放标定其占比（R7 定的前置：>5% 先收紧 prompt 引用格式）。
    本用例把该行为钉住：若将来收紧（如加法条白名单），此断言应随之更新。
    """
    rep = check_citations("依据《网络安全法》第二十一条……", KNOWN)
    assert not rep.ok, "当前形态判定下，法条转引必然被判未命中（已知误报）"
    assert "中华人民共和国网络安全法" not in rep.cited  # 仅记录它是漏报形态
