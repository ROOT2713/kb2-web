"""
Fee-related utility functions for kb2-web query pipeline.

Core concerns (post-D2-B-simplification, 2026-07-30):
1. _FEE_WHITELIST — fee query keywords for retrieval.py (skip synonym expansion)
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

# ── 费用查询白名单（供 retrieval.py 导入，单点维护） ──
# 检测用户查询是否为费用类，命中时跳过同义词扩展避免"GB"等稀释
_FEE_WHITELIST = [
    "造价", "取费", "费用", "费率", "收费",
    "验收测评", "验收评测", "检测费", "测评费", "评测费",
    "审计费", "管理费", "设计费", "监理费", "招标",
    "等保", "密评", "咨询费",
    "商密", "商用密码", "密码应用",
]

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
