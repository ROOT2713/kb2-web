"""Query decomposer — detect and split multi-topic queries into sub-queries.

Architecture:
  query() -> decompose(q) -> [sub_q1, sub_q2, ...]
         -> for each sub_q: recall + BM25 (parallel)
         -> merge_dedup(all_results)
         -> rrf_merge -> rerank -> answer
"""

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# ── Multi-topic detection patterns ──
_MULTI_PATTERNS = [
    re.compile(r'[+＋、和与及跟]'),                    # A+B+C pattern
    re.compile(r'(?:分别|各自|都有哪些|有哪些方面)'),    # explicit multi
    re.compile(r'(费|价格|标准|要求|方法)\w*(?:费|价格|标准|要求|方法|流程)'),  # A费+B费
    re.compile(r'[？?].{0,10}[？?]'),                    # multiple question marks
]

# ── Split separators (ordering matters: longer match first) ──
_SPLIT_PATTERN = re.compile(
    r'(?:以及|还有|另外|以及|跟)'  # multi-char first
    r'|[+＋、和]'                  # single-char
)

# ── Common suffix patterns shared across all sub-questions ──
_SUFFIX_PATTERNS = [
    re.compile(r'(各[自是]?[多多少]?[少]?)\s*$'),
    re.compile(r'(分别[是]?)\s*$'),
    re.compile(r'(各[自]?)是?多[少]钱\s*$'),
    re.compile(r'(各[自]?)是?什么\s*$'),
]


def detect_multi_topic(q: str) -> bool:
    """Check if query contains multiple independent sub-questions."""
    for pat in _MULTI_PATTERNS:
        if pat.search(q):
            return True
    return False


def split_sub_queries(q: str) -> List[str]:
    """Split a compound query into independent sub-queries.

    Examples:
      "验收测评费+等保费+密评费各是多少"
        → ["验收测评费是多少", "等保费是多少", "密评费是多少"]

      "验收测评费和等保费分别是多少"
        → ["验收测评费是多少", "等保费是多少"]

    Strategy:
      1. Extract and remove shared suffix ('各是多少', '分别', etc.)
      2. Split by connectors (+/、/和/以及/etc.)
      3. Append a generic question word to each part if no explicit question
      4. Max 4 sub-queries
    """
    q_stripped = q.strip()
    if not q_stripped:
        return []

    # ── Step 1: Extract shared suffix ──
    suffix = ""
    for pat in _SUFFIX_PATTERNS:
        m = pat.search(q_stripped)
        if m:
            suffix = m.group(1)
            q_stripped = q_stripped[:m.start()].strip()
            break

    # ── Step 2: Detect trailing generic question pattern ──
    # "A、B、C是多少" → the "是多少" is shared
    generic_q = ""
    for gq in ["是多少", "是什么", "有什么", "有哪些", "怎么做", "怎么收费", "怎么算", "多少钱"]:
        if q_stripped.endswith(gq):
            generic_q = gq
            q_stripped = q_stripped[:-len(gq)].strip()
            break

    # ── Step 3: Split ──
    parts = _SPLIT_PATTERN.split(q_stripped)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return [q]  # not compound after all

    # ── Step 4: Reconstruct each sub-query ──
    result = []
    question_word = suffix or generic_q or "是什么"
    for p in parts:
        # Check if part already has a question word embedded
        has_own_q = any(
            kw in p for kw in ["多少", "什么", "怎么", "哪些", "谁", "何时", "何处", "为何"]
        )
        if has_own_q:
            result.append(p)
        else:
            result.append(f"{p}{question_word}")

    # Max 4 queries
    return result[:4]
