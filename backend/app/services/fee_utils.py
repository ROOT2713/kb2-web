"""
Fee-related utility functions for kb2-web query pipeline.

Core concerns (post-D2-B-simplification, 2026-07-30):
1. fee_intent() — 全库唯一费用意图闸门（retrieval 同义词扩展 / 上下文注入共用）
2. filter_conflicting_fee_types() — cross-type post-filter on all_results
3. _FEE_KEYWORDS — fee detection list for _fee_rules prompt injection

D2-B (find_fee_relevant_chunks + injection) removed 2026-07-30.
Normal pipeline (semantic + BM25 + RRF) + _fee_rules prompt now handles fee queries.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── 费用查询关键词（查询检测用） ──
# 2026-07-28 实证：含"佛山""东莞"确保地市特定造价查询被正确标记
_FEE_KEYWORDS = [
    "造价", "取费", "费用", "费率", "收费",
    "验收测评", "验收评测", "检测费", "测评费", "评测费",
    "审计费", "管理费", "设计费", "监理费", "招标",
    "等保", "密评", "咨询费",
    "商密", "商用密码", "密码应用",
    "概算", "佛山", "东莞", "造价指南", "概算编制",
    "概算指南", "取费标准", "设计费比例", "比例范围",
    "计价", "计价表", "投资比例",
]

# ── [2026-10-13] _FEE_WHITELIST 已删除：检索层同义词扩展判定
# 统一改走 fee_intent()，消除「检索层按裸主题词判费用、注入层不判」的层间不一致。
# ── 费用类型互斥表 ──
# 当用户问某类费用时，应降低含冲突费用类型的 chunk 权重
# key=查询检测到的费用类型, value=该类型的冲突费用类型集合
# 命名原则：单向互斥（等保→排斥验收测评，但验收测评→不排斥等保）
_FEE_TYPE_EXCLUSIONS = {
    "等保":      {"验收测评", "验收评测"},
    "验收测评":   set(),
    "验收评测":   set(),
}


def _detect_fee_type(query: str) -> Optional[str]:
    """从查询中检测费用类型关键词。"""
    # 特化词优先（"验收测评"先于"测评"、"等保"先于"费用"）
    priority = ("验收测评", "验收评测", "商用密码", "商密评估",
                "密评", "等保", "检测费", "测评费", "评测费",
                "监理费", "设计费", "审计费", "咨询费")
    for kw in priority:
        if kw in query:
            return kw
    # 通用关键词
    for kw in _FEE_KEYWORDS:
        if kw in query:
            return kw
    return None


def filter_conflicting_fee_types(
    all_results: list[dict],
    query: str,
) -> list[dict]:
    """
    Cross-type fee filter — post-filter on all_results vector chunks.

    Detects the fee type from the query, then demotes chunks that contain
    conflicting fee types (e.g. "验收测评" chunks when query asks "等保").
    Does NOT delete chunks — only moves conflicting ones to the end of the list
    so LLM still sees them but they're less prominent.

    Returns the same list (modified in-place).
    """
    if not all_results:
        return all_results

    fee_type = _detect_fee_type(query)
    if not fee_type or fee_type not in _FEE_TYPE_EXCLUSIONS:
        return all_results

    conflicting = _FEE_TYPE_EXCLUSIONS[fee_type]
    if not conflicting:
        return all_results

    filtered = []
    demoted = []

    for chunk in all_results:
        text = chunk.get("text", "") or ""
        # 检测 chunk 是否包含冲突费用类型关键词
        has_conflict = any(cf in text for cf in conflicting)
        # 若 chunk 也提及查询费用类型本身，则视为兼容（如"等级保护测评服务(含验收测评)"）
        has_self = fee_type in text
        if has_conflict and not has_self:
            demoted.append(chunk)
        else:
            filtered.append(chunk)

    # 替换原列表：兼容的在前，冲突的在后
    all_results[:] = filtered + demoted
    return all_results


# ── [闸门统一 2026-10-13] 费用意图闸门 v5（全库唯一权威）────────────────
# 背景：全库曾有 8 处各自维护的费用关键词表（5 处在 query_engine.py 内联），
#   彼此不一致、且都含裸「等保/密评」，实测生产真实查询 精确率 50% / 召回率 71%
#   —— 10 个「带主题词但问的不是钱」误报 + 4 个真费用题漏判。
# v5.1 三源实测：真实查询(80) 100%/100%、留出集(100) 100%/100%（2026-10-13 备份目录重测）。
# 设计原则（泛化能成立的原因）：
#   1. 主题词（等保/密评/商密…）本身不算费用意图，必须再配「钱」的线索
#      → 消掉全部 10 个主题词误报
#   2. 「费」字用否定环视排除 消费/免费/浪费
#   3. 泛化「X费 + 费用动作」而非穷举 监理费/代理费…全词
#      → 覆盖「监理服务费怎么算」「招标代理费怎么收」这类词表穷举不完的写法
_STRONG_FEE = ("费率", "取费", "收费", "计费", "基价", "计价", "计取", "补贴",
               "费用", "每U")
# 泛化金钱词：本身不是取费词，须与费用词共现才算费用意图。
# （CC 评审 2026-10-13：单凭「金额」会把「…资金调整数额不超过总金额多少比例…」误判）
_MONEY_ONLY_FEE = ("金额", "比例", "万元", "价格", "报价")
_FEE_CO = ("费用", "费率", "取费", "收费", "计价", "造价", "概算", "预算",
           "基价", "计取")
_TOPIC_FEE = ("等保", "密评", "商密", "密码应用", "验收测评", "验收评测")
_MONEY_CUE = ("多少钱", "多少万", "多少元", "多少费用", "多少预算",
              "多少资金", "多少补贴")
_FEE_CHAR_RE = re.compile(r"(?<!消)(?<!免)(?<!浪)费")
_FEE_ACT = ("怎么算", "怎么收", "怎么取", "怎么定", "怎么计", "多少钱", "如何计",
            "收费标准", "取费", "费率", "计取", "计价", "多少", "价格", "金额",
            "标准", "比例", "预算", "费用", "概算")
_COST_CUE = ("费用", "费率", "取费", "收费", "计价", "万元", "金额", "比例",
             "预算", "多少钱", "补贴", "构成", "概算")
_QTY_ACT = ("怎么编", "怎么算", "多少钱", "比例", "取费", "金额", "万元", "标准", "多少")


def fee_intent(q: str) -> bool:
    """费用意图闸门 v5.1 —— 全库唯一权威（真实集80 100%/100%，留出集100 100%/100%）。

    v5.1 相对 v5 的两处修订（CC 评审 2026-10-13）：
      · 加回裸「费用」到 STRONG —— v5 漏掉「监理费用」这类裸名词
      · 金钱词（金额/比例/万元/价格/报价）降级为须与费用词共现
        —— 消掉「…资金调整数额不超过总金额多少比例…」这唯一残余误报
    注意：geo 词（佛山/东莞）不单独触发 —— 提及地市 ≠ 问费用。
    """
    if not q:
        return False
    if any(k in q for k in _STRONG_FEE):
        return True
    if any(k in q for k in _MONEY_ONLY_FEE) and any(c in q for c in _FEE_CO):
        return True
    for m in _FEE_CHAR_RE.finditer(q):         # 泛化「X服务费/代理费」类
        if any(a in q[m.end():m.end() + 8] for a in _FEE_ACT):
            return True
    if "造价" in q and any(c in q for c in _COST_CUE):
        return True
    if any(k in q for k in _TOPIC_FEE) and (
            any(m in q for m in _MONEY_CUE) or _FEE_CHAR_RE.search(q)):
        return True
    if ("概算" in q or "预算" in q) and any(a in q for a in _QTY_ACT):
        return True
    return False
