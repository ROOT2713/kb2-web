"""Phase C1: Standard Number Exact Match Boost.

When user query contains an exact standard number (GB/T 22239, JJF 1059.1, etc.),
boost retrieval by:
1. Detect standard numbers in query (reuse _STD_PATTERN regex)
2. For each detected std-num, look up matching documents in DB by title match
3. Inject those docs' parent_chunks into doc_facts so they're guaranteed in context
4. Boost their effective rank to top of the pile

This fixes the recall=0 cases where the standard exists in DB with 32 chunks but
Hindsight ranking pushes it out of top-5.
"""

import re
import logging
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text

logger = logging.getLogger(__name__)


# Reuse same regex from query.py (avoid circular import — keep duplicated)
_STD_PATTERN = re.compile(
    r'(GB\s*/?\s*T?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|ISO(?:\s*/\s*IEC)?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|(?:YD|SJ|GA|HJ|CJJ|JGJ|WS|GY|JJF|JJG)\s*/?\s*T?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|T\s*/\s*EGAG\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|TEGAG\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|GDZW\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|STC[\w\-]+'
    r'|DB\d+[\w\-]*'
    r'|[一-鿿]+〔\d+〕\d+号)',
    re.IGNORECASE,
)


def extract_standard_numbers(q: str) -> list[str]:
    """Extract all standard numbers from a query string.

    Returns normalized forms (uppercase, no extra spaces).
    """
    if not q:
        return []
    matches = _STD_PATTERN.findall(q)
    # Normalize: uppercase, strip spaces, then dedupe preserving order
    normalized = []
    seen = set()
    for m in matches:
        norm = re.sub(r'\s+', '', m.upper())
        if norm not in seen:
            seen.add(norm)
            normalized.append(m.strip())  # keep original form for matching
    return normalized


def find_docs_by_standard_number(db: Session, std_num: str, bank: str = "all") -> list[dict]:
    """Find active documents whose title matches a standard number.

    Uses fuzzy match: strip spaces/slashes/+/_/∕ from both title and std_num.
    Returns list of {doc_id, title, type} dicts.
    """
    if not std_num:
        return []

    # Normalize std_num for matching: uppercase, strip separators
    norm_std = re.sub(r'[/\s_\-+∕]', '', std_num.upper())
    if len(norm_std) < 4:  # Avoid matching too-short tokens
        return []

    # Query active gb_standard / regulation docs and fuzzy match in Python
    # (SQL LIKE can't easily handle all separator variants)
    sql = """SELECT doc_id, title, doc_type 
             FROM documents 
             WHERE status='active' AND searchable=1 
               AND doc_type IN ('gb_standard', 'regulation')"""
    params = {}
    if bank != "all":
        sql += " AND bank=:bank"
        params["bank"] = bank
    rows = db.execute(sa_text(sql), params).fetchall()

    matches = []
    for doc_id, title, doc_type in rows:
        if not title:
            continue
        # Normalize title for matching
        norm_title = re.sub(r'[/\s_\-+∕\.,\(\)（）]', '', title.upper())
        if norm_std in norm_title:
            matches.append({"doc_id": doc_id, "title": title, "doc_type": doc_type})
    return matches


def fetch_doc_chunks(db: Session, doc_id: str, max_chunks: int = 5) -> list[tuple]:
    """Fetch top N parent_chunks for a doc_id.

    Returns list of (parent_text, parent_idx) tuples.
    Prefers non-cover, non-toc chunks (skip parent_idx 0-2 if many chunks exist).
    """
    rows = db.execute(
        sa_text(
            "SELECT parent_idx, parent_text FROM parent_chunks "
            "WHERE doc_id=:doc_id ORDER BY parent_idx"
        ),
        {"doc_id": doc_id},
    ).fetchall()
    if not rows:
        return []

    # If many chunks: skip first 2 (likely cover/toc) and take middle-substantive ones
    if len(rows) > 5:
        chunks = rows[2:2 + max_chunks]
    else:
        chunks = rows[:max_chunks]

    return [(text, idx) for idx, text in chunks if text and text.strip()]


def boost_exact_standards(
    db: Session,
    q: str,
    doc_facts: dict,
    title_map: dict,
    bank: str = "all",
    max_chunks_per_doc: int = 5,
) -> dict:
    """Mutate doc_facts to inject exact-standard-matched docs.

    Returns stats: {"std_nums_detected": int, "docs_injected": int, "chunks_injected": int}
    """
    stats = {"std_nums_detected": 0, "docs_injected": 0, "chunks_injected": 0}

    std_nums = extract_standard_numbers(q)
    if not std_nums:
        return stats
    stats["std_nums_detected"] = len(std_nums)
    logger.info("[C1-StdBoost] Detected standard numbers in query: %s", std_nums)

    seen_doc_ids = set(doc_facts.keys())

    for std_num in std_nums:
        matches = find_docs_by_standard_number(db, std_num, bank=bank)
        if not matches:
            logger.info("[C1-StdBoost] No DB match for std '%s'", std_num)
            continue

        for match in matches[:3]:  # Take top 3 matches per std_num (e.g. 22239 might have 多个 doc)
            doc_id = match["doc_id"]
            title = match["title"]

            chunks = fetch_doc_chunks(db, doc_id, max_chunks=max_chunks_per_doc)
            if not chunks:
                logger.info("[C1-StdBoost] No chunks for '%s'", title)
                continue

            # Inject into title_map
            if doc_id not in title_map:
                title_map[doc_id] = title

            # If doc already in doc_facts, boost to front by recreating dict
            if doc_id in seen_doc_ids:
                logger.info("[C1-StdBoost] Doc '%s' already in search, boosting to front", title[:60])
                new_facts = {doc_id: doc_facts[doc_id]}
                for did, facts in doc_facts.items():
                    if did != doc_id:
                        new_facts[did] = facts
                doc_facts.clear()
                doc_facts.update(new_facts)
                stats["docs_boosted"] = stats.get("docs_boosted", 0) + 1
                continue

            # Inject chunks. Format matches what _build_search_context produces:
            # tuples of (text_val, doc_name, cleaned_excerpt, parent_idx)
            # Insert at FRONT of doc_facts so this doc ranks top in _generate_answer
            chunks_to_inject = []
            for text, idx in chunks:
                cleaned = text[:500]
                chunks_to_inject.append((text, title, cleaned, idx))

            # Rebuild doc_facts with std-boosted doc at front
            new_facts = {doc_id: chunks_to_inject}
            for did, facts in doc_facts.items():
                if did != doc_id:
                    new_facts[did] = facts
            doc_facts.clear()
            doc_facts.update(new_facts)
            stats["chunks_injected"] += len(chunks_to_inject)

            seen_doc_ids.add(doc_id)
            stats["docs_injected"] += 1
            logger.info(
                "[C1-StdBoost] Injected '%s' (%d chunks) for std '%s' at FRONT",
                title[:60], len(chunks), std_num,
            )

    return stats
