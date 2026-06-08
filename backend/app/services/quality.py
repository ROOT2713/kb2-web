"""Document quality assessment and profiling.

Ported from: kb-web server.py profile_document() L1892-L1993,
             assess_quality() L1830-L1887
"""

import logging
import re
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def assess_quality(text: str) -> dict:
    """评估文本质量，返回 {score, total_chars, meaningful_chars, issues}"""
    if not text or len(text.strip()) < 50:
        return {"score": 0, "total_chars": len(text), "meaningful_chars": 0,
                "issues": ["文本过短（<50字符）"]}

    total = len(text)
    meaningful = 0
    garbage_chars = 0  # replacement char U+FFFD
    repeated_runs = 0

    for i, ch in enumerate(text):
        code = ord(ch)
        # CJK Unified Ideographs + Extension A
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            meaningful += 1
        # ASCII letters/digits
        elif (0x30 <= code <= 0x39) or (0x41 <= code <= 0x5A) or (0x61 <= code <= 0x7A):
            meaningful += 1
        # Common punctuation
        elif 0x20 <= code <= 0x2F or 0x3A <= code <= 0x40:
            meaningful += 1
        elif code in (0x3001, 0x3002, 0xFF0C, 0xFF0E, 0xFF1A, 0xFF1B, 0xFF08, 0xFF09, 0x0A):
            meaningful += 1
        # Replacement character
        elif code == 0xFFFD:
            garbage_chars += 1
        # Repeated char detection (3+ same in a row, skip spaces/newlines)
        if i >= 2 and text[i] == text[i-1] == text[i-2] and ord(text[i]) > 32 and ord(text[i]) != 0x0A:
            repeated_runs += 1

    # Scores
    garbage_ratio = garbage_chars / max(total, 1)
    meaningful_ratio = meaningful / max(total, 1)
    repeated_ratio = repeated_runs / max(total, 1)

    # Weighted score
    score = 100 * (meaningful_ratio * 0.7 + (1.0 - garbage_ratio) * 0.2 + (1.0 - repeated_ratio) * 0.1)
    score = max(0, min(100, int(score)))

    issues = []
    if garbage_ratio > 0.05:
        issues.append(f"存在 {garbage_chars} 个替换字符(�)，占比 {garbage_ratio*100:.1f}%")
    if meaningful_ratio < 0.3:
        issues.append(f"有效字符占比仅 {meaningful_ratio*100:.1f}%，疑似乱码")
    if repeated_ratio > 0.1:
        issues.append(f"重复字符占比 {repeated_ratio*100:.1f}%，可能存在编码损坏")
    if len(text) < 200:
        issues.append(f"文本仅 {len(text)} 字符，内容可能不完整")
    if not issues:
        issues.append("文本质量正常")

    return {
        "score": score,
        "total_chars": total,
        "meaningful_chars": meaningful,
        "issues": issues,
    }


# ─── Adaptive Chunking: Document Profiling ────────────────────────

def profile_document(text: str) -> dict:
    """Analyze document structure and return profiling info.

    Returns:
        {
            "doc_type": "gb_standard" | "regulation" | "generic",
            "headings": [(level: int, title: str, pos: int), ...],
            "confidence": float  # 0.0 ~ 1.0
        }
    """
    lines = text.split("\n")

    # ── GB Standard detection ──
    # Pattern: numbered headings like "## 4 总则", "## 5.1 xxx", "5.3.2 xxx"
    # Also: appendix headings "## 附录A", "## A.1 xxx"
    re_gb_md_heading = re.compile(r'^(#{1,4})\s+(\d+(?:\.\d+)*)\s+(.*)$')        # ## 4 总则
    re_gb_raw_heading = re.compile(r'^(\d+(?:\.\d+)*)\s*(.{1,60})$')             # 4.1 总则 or 1范围 (no ##)
    re_gb_appendix_md = re.compile(r'^(#{1,4})\s+(附录[A-Z])\s*(.*)$')           # ## 附录A
    re_gb_appendix_sub = re.compile(r'^(#{1,4})\s+([A-Z]\.\d+)\s*(.*)$')         # ## A.1 xxx
    re_gb_raw_appendix = re.compile(r'^([A-Z]\.\d+)\s+(.{1,60})$')               # A.1 xxx (no ##)

    gb_headings = []
    for i, line in enumerate(lines):
        line_stripped = line.rstrip()
        pos = sum(len(lines[j]) + 1 for j in range(i))  # byte offset in text

        # Markdown numbered headings
        m = re_gb_md_heading.match(line_stripped)
        if m:
            level = len(m.group(1))  # number of # characters
            title = f"{m.group(2)} {m.group(3)}".strip()
            gb_headings.append((level, title, pos))
            continue

        # Appendix markdown headings: ## 附录A
        m = re_gb_appendix_md.match(line_stripped)
        if m:
            level = len(m.group(1))
            title = f"{m.group(2)} {m.group(3)}".strip() if m.group(3) else m.group(2)
            gb_headings.append((level, title, pos))
            continue

        # Appendix sub-headings markdown: ## A.1 xxx
        m = re_gb_appendix_sub.match(line_stripped)
        if m:
            level = len(m.group(1))
            title = f"{m.group(2)} {m.group(3)}".strip() if m.group(3) else m.group(2)
            gb_headings.append((level, title, pos))
            continue

        # Raw numbered headings (no markdown prefix)
        m = re_gb_raw_heading.match(line_stripped)
        if m:
            title = f"{m.group(1)} {m.group(2)}".strip()
            gb_headings.append((1, title, pos))
            continue

        # Raw appendix sub-headings (no markdown prefix): A.1 xxx
        m = re_gb_raw_appendix.match(line_stripped)
        if m:
            title = f"{m.group(1)} {m.group(2)}".strip()
            gb_headings.append((1, title, pos))
            continue

    # ── Regulation detection ──
    re_article_cn = re.compile(r'^第[一二三四五六七八九十百千零\d]+条')
    re_article_num = re.compile(r'^第(\d+)条')
    regulation_count = 0
    regulation_headings = []
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        pos = sum(len(lines[j]) + 1 for j in range(i))
        if re_article_cn.match(line_stripped) or re_article_num.match(line_stripped):
            regulation_count += 1
            # Extract article title (first 80 chars of the line)
            title = line_stripped[:80]
            regulation_headings.append((1, title, pos))

    # ── Classification ──
    # Count unique numbered sections (top-level like "1", "2", ... not sub-levels)
    top_level_gb = len(set(h[1].split()[0].split('.')[0] for h in gb_headings if h[1]))
    total_gb = len(gb_headings)

    doc_type = "generic"
    headings = []
    confidence = 0.0

    if total_gb >= 3:
        doc_type = "gb_standard"
        headings = gb_headings
        confidence = min(1.0, total_gb / 10)
    elif regulation_count >= 3:
        doc_type = "regulation"
        headings = regulation_headings
        confidence = min(1.0, regulation_count / 10)

    return {
        "doc_type": doc_type,
        "headings": headings,
        "confidence": confidence,
    }
