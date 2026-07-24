"""
Fee-related utility functions for kb2-web query pipeline.

Core concerns:
1. D2-B injection: find fee rate table chunks instead of LIMIT 3
2. Query-amount alignment: match query's investment amount to doc's tier ranges
3. Formula detection: identify which formula pattern a fee table uses

Replaces the old approach of hardcoding "速算增加额" in _tier_hint
and the naive LIMIT 3 parent_chunks scan.
"""

import logging
from typing import Optional

from sqlalchemy import text as sa_text

from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

# Fee table indicator keywords — chunks containing these are likely rate tables
_FEE_TABLE_KEYWORDS = [
    "表 ",        # Chinese table prefix (space intentional — "表 5-7")
    "费率",       # rate/fee rate
    "计费额",     # charge base amount
    "收费基价",   # base charge price
    "费用基价",   # cost base price
    "基价表",     # base price table
    "监理费用",   # supervision fee
    "评测费率",   # evaluation rate
    "评估费率",   # assessment rate
    "验收测评",   # acceptance testing
    "验收评测",   # acceptance testing (variant)
    "等保评测",   # grade protection testing
    "源代码审计", # source code audit
    "建设单位管理费", # construction unit management fee
    "设计咨询费", # design consulting fee
    "招标代理",   # bidding agency
    "最终费用",   # final fee (usually at end of rate table)
    "插入法",     # interpolation method
    "计算公式",   # calculation formula
    "内插",       # interpolation
    "D×g×",      # V = D × g × (1-Z) pattern
    "V=D",        # V = D × formula pattern
    "V=D×g",      # V = D × g pattern (验收评测费)
    "商用密码",   # commercial cryptography
    "商密评估",   # commercial crypto assessment
    "密评",       # crypto assessment (abbr)
    "密码应用",   # crypto application
]

# Mismatch penalty keywords — chunks containing these are likely NOT the fee table
# but instead metadata / front-matter / adjustment instructions that distract LLM
_FEE_MISMATCH_KEYWORDS = [
    "调整系数",
    "编制说明",
    "前言",
    "编委会",
    "封面",
]

# Formula definition keywords — chunks near these contain the actual formula text
_FORMULA_KEYWORDS = [
    "计算公式",
    "直线内插",
    "插入法",
    "y=y₁",
    "y=y1",
    "V=",
    "V=D",
    "最终费用(V)",  # stronger — appears in 验收评测/等保 tables
    "费用基价",
    "收费基价",
]


def _score_fee_chunk(text: str, amount_keywords: list[str]) -> int:
    """
    Score a parent_chunk on how likely it contains useful fee rate table content.
    
    Scoring dimensions:
    - Contains table + rate indicators: +2 per match
    - Contains formula/calculation: +3
    - Contains query's amount keyword in context: +2
    - Contains specific fee type keywords: +1 per match (capped)
    - Very short (<200 chars): -2 (too fragmented)
    """
    score = 0
    text_lower = text.lower()
    
    # Fee table keywords
    _fee_kw_count = 0
    for kw in _FEE_TABLE_KEYWORDS:
        if kw in text:
            if kw in ("表 ", "费率", "计费额", "密码"):
                score += 2  # Stronger signal
            else:
                score += 1
            _fee_kw_count += 1
            if _fee_kw_count >= 5:  # Cap at 5 matches
                break
    
    # Formula keywords — strong signal
    for kw in _FORMULA_KEYWORDS:
        if kw in text:
            score += 3
            break  # cap at one formula bonus
    
    # Mismatch penalty — if chunk has WRONG fee type metadata/front-matter
    for kw in _FEE_MISMATCH_KEYWORDS:
        if kw in text:
            score -= 5
    
    # Amount alignment — the query's amount value
    for akw in amount_keywords:
        if akw in text:
            score += 2
    
    # Penalize very short fragments
    if len(text) < 200:
        score -= 2
    
    # Size normalization — penalize huge but sparse chunks
    if len(text) > 2000:
        score = int(score * (2000 / len(text)))  # Linear penalty for chunks > 2KB

    return score


def find_fee_relevant_chunks(
    doc_ids: list[str],
    amount_keywords: list[str] | None = None,
    max_chunks: int = 8,
    fee_type_keywords: list[str] | None = None,
) -> list[dict]:
    """
    Find parent_chunks that contain fee rate table content for the given docs.
    
    Instead of LIMIT 3 (which hits cover/front-matter), this:
    1. Scans ALL parent_chunks for fee-relevant content
    2. Scores each chunk by keyword density + formula presence
    3. Returns top-N chunks with scores
    
    Returns:
        list of {"doc_id": str, "title": str, "text": str, 
                 "parent_idx": int, "score": int, "source": str}
    """
    if not doc_ids:
        return []
    
    amount_keywords = amount_keywords or []
    results: list[dict] = []
    
    try:
        pdb = SessionLocal()
        try:
            # Build query parameters
            # SAFETY: doc_ids come from internal vector search results (all_results),
            # NOT from direct user input. The conditions use parameterized queries
            # with named bind params (:{key}), not string interpolation of values.
            # The f-string only constructs the SQL template pattern, not the values.
            conditions = []
            params: dict = {}
            for i, did in enumerate(doc_ids):
                key = f"did{i}"
                conditions.append(f"p.doc_id = :{key}")
                params[key] = did
            
            if not all(isinstance(d, str) for d in doc_ids):
                raise TypeError(
                    f"doc_ids must be strings, got {set(type(d).__name__ for d in doc_ids)}"
                )
            
            where_clause = " OR ".join(conditions)
            
            rows = pdb.execute(sa_text(f"""
                SELECT p.doc_id, p.parent_idx, p.parent_text, d.title
                FROM parent_chunks p
                JOIN documents d ON p.doc_id = d.doc_id
                WHERE ({where_clause})
                  AND length(p.parent_text) > 100
                ORDER BY p.parent_idx
            """), params).fetchall()
        finally:
            pdb.close()
        
        # Score and collect
        for did, pidx, ptext, title in rows:
            score = _score_fee_chunk(ptext, amount_keywords)
            # Fee-type specific boost: if user asked about a specific service type
            # (e.g. 验收测评), give extra points to chunks that mention it
            if fee_type_keywords:
                for fk in fee_type_keywords:
                    if fk in ptext:
                        score += 4  # Bigger boost than generic fee keywords
                # Cross-type exclusion: if user asked "等保", penalize "验收测评" chunks
                # These are distinct service types in cost guides and should not be conflated
                _exclusion_map = {
                    "等保": ["验收测评", "验收评测"],
                    "验收测评": [],
                    "验收评测": [],
                }
                for fk in fee_type_keywords:
                    if fk in _exclusion_map:
                        for _excl_kw in _exclusion_map[fk]:
                            if _excl_kw in ptext:
                                score -= 15  # Strong penalty — wrong fee type
                                break
            if score > 0:
                results.append({
                    "doc_id": did,
                    "parent_idx": pidx,
                    "title": title,
                    "text": ptext,
                    "score": score,
                    "source": "industry_fallback",
                })
        
        # Dedup by content prefix — keep only highest-scored per doc+content
        seen_prefixes = {}
        deduped = []
        for r in results:
            key = f"{r['doc_id']}:{r['text'][:200]}"
            if key in seen_prefixes:
                continue
            seen_prefixes[key] = True
            deduped.append(r)
        results = deduped
        
        # Sort by score descending, then by parent_idx (within same score)
        results.sort(key=lambda r: (-r["score"], r["parent_idx"]))
        
        # ── Per-doc fairness: ensure at least 1 chunk from each doc ──
        # Prevents a single doc (e.g. 东莞) from crowding out others (e.g. 佛山)
        # Phase 1: reserve 1 top chunk per doc
        top = []
        reserved_ids = set()
        for r in results:
            if r["doc_id"] not in reserved_ids:
                top.append(r)
                reserved_ids.add(r["doc_id"])
                if len(top) >= max_chunks:
                    break
        
        # Phase 2: fill remaining slots with next-best chunks (round-robin by remaining capacity)
        if len(top) < max_chunks:
            remaining_capacity = max_chunks - len(top)
            # Flat top-N from remaining unselected chunks
            unselected = [r for r in results if r["doc_id"] in reserved_ids and r not in top]
            unselected_sorted = sorted(unselected, key=lambda r: (-r["score"], r["parent_idx"]))
            top.extend(unselected_sorted[:remaining_capacity])
        
        if top:
            logger.info(
                "[D2-B-FIX] Found %d fee-relevant chunks (scored %d) from %d docs, selected %d",
                len(results), max(r["score"] for r in results) if results else 0,
                len(doc_ids), len(top),
            )
        else:
            logger.info("[D2-B-FIX] No fee-relevant chunks found among %d docs", len(doc_ids))

        return top
    
    except Exception as e:
        logger.warning("[D2-B-FIX] find_fee_relevant_chunks failed: %s", e)
        return []


def detect_fee_formula_type(chunks: list[dict]) -> list[str]:
    """
    Detect which formula types are present in the collected chunks.
    Returns list of detected formula pattern names.
    
    Patterns (from the 造价指导书 第三部分):
    - "直线内插" — linear interpolation (设计费 表5-7, 监理费 表5-9/5-10)
    - "费率比例" — V = D × g × (1-Z) (验评费 表5-48/5-49, 等保费 表5-47)
    - "阶梯费率" — tiered percentage (建设单位管理费 表5-41)
    - "固定单价" — fixed unit price (源代码审计 表5-65, 安全评测 表5-44)
    """
    combined = " ".join(c["text"] for c in chunks)
    
    patterns = []
    
    if "内插" in combined or "插入" in combined or "y=y" in combined:
        patterns.append("直线内插")
    
    if "D×g×" in combined or "V=D" in combined or "D × g" in combined:
        patterns.append("费率比例")
    
    if "费率表" in combined and "万以下" in combined:
        patterns.append("阶梯费率")
    
    if "收费标准" in combined and "元/次" in combined:
        patterns.append("固定单价")
    
    return patterns


def build_fee_context_prompt(chunks: list[dict], query: str) -> str:
    """
    Build a fee-contextual prompt snippet based on the collected chunks.
    
    Strategy: if we found formula-related chunks, generate a brief
    formula guidance snippet. Otherwise, no special guidance needed.
    """
    if not chunks:
        return ""
    
    patterns = detect_fee_formula_type(chunks)
    if not patterns:
        return ""
    
    # Map detected patterns to guidance text
    guidance = []
    
    if "直线内插" in patterns:
        guidance.append(
            "- 直线内插法：费用 = y₁ + (x-x₁)/(x₂-x₁) × (y₂-y₁)\n"
            "  （在计费额x所在档位(x₁,y₁)~(x₂,y₂)之间按比例计算）"
        )
    
    if "费率比例" in patterns:
        guidance.append(
            "- 费率比例法：V = D × g × (1-Z)\n"
            "  （D为规模/投资额，g为费率，Z为调衡系数，均按文档中的费率表取值）"
        )
    
    if "阶梯费率" in patterns:
        guidance.append(
            "- 阶梯费率法：按投资额所在档位，逐档累加计算\n"
            "  （每档费用 = 该档金额区间 × 该档费率，各档费用相加）"
        )
    
    if "固定单价" in patterns:
        guidance.append(
            "- 固定单价法：V = 单价 × 数量 × (1-Z)\n"
            "  （按文档中给出的单价和数量计算，注意是否适用调衡系数）"
        )
    
    if not guidance:
        return ""
    
    result = (
        "【费用计算引导】\n"
        "文档中包含以下计费方式，请根据文档原文中的费率表和公式计算：\n"
        + "\n".join(guidance) +
        "\n\n"
        "【核心要求】\n"
        "1. 优先查找并直接引用文档中的费率表具体数据和公式\n"
        "2. 文档中每个费率表后面通常跟着计算公式和具体算例，请直接使用文档原公式\n"
        "3. 如果文档有示例计算，按照示例的步骤执行\n"
        "4. 必须标注每个关键数字的来源（文档名称+表号，如《造价指导书》表5-7）\n"
        "5. 'X万以下'包含X万本身，'X万以上'不包含X万\n"
    )
    
    return result
