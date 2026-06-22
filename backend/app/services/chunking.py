"""Text chunking strategies — heading-based, parent-child, excel-row.

Ported from: kb-web server.py L1890-L2598
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    text: str
    index: int
    heading: str = ""
    parent_idx: Optional[int] = None
    metadata: dict = field(default_factory=dict)


# ─── Internal dict-based functions (preserving v1 logic verbatim) ────────


def heading_chunk(text: str, profile: dict, min_child_size: int = 200, max_parent_size: int = 3000) -> list:
    """Split document by semantic headings. Returns same format as parent_child_chunk.

    For gb_standard:
      - child = content under each leaf heading (X.X.X or X.X level)
      - parent = content under parent heading (X level), combining all its children
      - If a child is too small (< min_child_size), merge with next sibling
      - If a parent is too large (> max_parent_size), keep it as-is (don't split further)

    For regulation:
      - child = each article (第N条)
      - parent = group of 3-5 consecutive articles

    Returns same format as parent_child_chunk:
    [{"child": str, "parent": str, "child_index": int, "parent_index": int, "section_hint": str}]
    """
    headings = profile.get("headings", [])
    doc_type = profile.get("doc_type", "generic")

    if not headings:
        return []  # caller should fall back to parent_child_chunk

    if doc_type == "gb_standard":
        return _heading_chunk_gb(text, headings, min_child_size, max_parent_size)
    elif doc_type == "regulation":
        return _heading_chunk_regulation(text, headings)
    else:
        return []


def _truncate_at_sentence_boundary(text: str, max_len: int = 800) -> str:
    """在 max_len ±20% 范围内找最近的句子结束符（。！？；\\n.!?）截断。

    若搜索范围内无句末标点，回退到硬截断 text[:max_len]。
    用于 _heading_chunk_gb 的 child_text/parent_text 截断（避免切在句子中间）。
    """
    if len(text) <= max_len:
        return text
    # 搜索范围 [max_len*0.8, max_len*1.2]，但不超过文本长度
    search_start = int(max_len * 0.8)
    search_end = min(int(max_len * 1.2), len(text))
    for boundary_char in ['\n', '。', '！', '？', '；', '.', '!', '?']:
        idx = text.rfind(boundary_char, search_start, search_end)
        if idx > 0:
            return text[:idx + 1]
    # 找不到句边界，硬截断
    return text[:max_len]


def _clause_split(text: str, max_child_size: int = 800) -> list:
    """对大文本按条款编号模式拆分为子块。

    检测模式：
    1. 嵌套编号: 5.1.1, 5.1.2, A.1.1 等
    2. 条款编号: 第1条, 第2条 等
    3. 字母编号: a) b) c) 或 (a) (b) (c)

    如果未检测到编号模式，按段落（空行）拆分。
    每个子块不超过 max_child_size。

    Returns: [{"text": str, "clause_id": str}, ...]
    """
    if len(text) <= max_child_size:
        return [{"text": text, "clause_id": ""}]

    lines = text.split("\n")

    # Pattern 1: 嵌套编号 (5.1.1, A.2.3, etc.)
    re_clause = re.compile(r'^(\d+(?:\.\d+)+|[A-Z]\.\d+(?:\.\d+)*)\s')

    # Pattern 2: 条款编号 (第N条)
    re_article = re.compile(r'^(第[一二三四五六七八九十百千零\d]+[条款章节])')

    # Pattern 3: 字母编号 a) b) c) 或 (a) (b) (c)
    re_letter = re.compile(r'^[（(]?[a-z][)）]')

    # Find clause boundaries
    boundaries = []  # [(line_idx, clause_id)]
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        m = re_clause.match(line_stripped)
        if m:
            boundaries.append((i, m.group(1)))
            continue
        m = re_article.match(line_stripped)
        if m:
            boundaries.append((i, m.group(1)))
            continue
        # Only match letter patterns if they appear at start of line
        # and we already have at least one other boundary type
        if boundaries and re_letter.match(line_stripped):
            boundaries.append((i, line_stripped[:10]))

    if len(boundaries) < 2:
        # No clause boundaries found, try splitting by paragraphs
        boundaries = []
        for i, line in enumerate(lines):
            if line.strip() == "" and i > 0 and lines[i - 1].strip() != "":
                boundaries.append((i, f"para-{i}"))

    if len(boundaries) < 2:
        # Still no boundaries, hard split at max_child_size
        chunks = []
        for start in range(0, len(text), max_child_size):
            chunk_text = text[start:start + max_child_size]
            chunks.append({"text": chunk_text, "clause_id": f"chunk-{start}"})
        return chunks

    # Extract clause texts
    clauses = []
    for idx, (line_idx, clause_id) in enumerate(boundaries):
        end_line = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        clause_text = "\n".join(lines[line_idx:end_line]).strip()
        if clause_text:
            # If clause is too large, truncate at sentence boundary
            clause_text = _truncate_at_sentence_boundary(clause_text, max_child_size)
            clauses.append({"text": clause_text, "clause_id": clause_id})

    return clauses if clauses else [{"text": text, "clause_id": ""}]



def _parse_section_number(title: str):
    """Extract the numeric part from a heading title for level comparison.

    Examples:
        "4 总则" → (4,)
        "5.1 xxx" → (5, 1)
        "5.1.2 xxx" → (5, 1, 2)
        "附录A xxx" → None (appendix)
        "A.1 xxx" → None (appendix sub)
    Returns tuple of ints or None.
    """
    m = re.match(r'(\d+(?:\.\d+)*)', title.strip())
    if m:
        return tuple(int(x) for x in m.group(1).split('.'))
    return None


def _heading_chunk_gb(text: str, headings: list, min_child_size: int = 200, max_parent_size: int = 3000) -> list:
    """Heading-based chunking for GB standard documents."""
    lines = text.split("\n")

    # Compute byte offsets for each heading position
    # (profile_document stores char offsets; we need to map to line-based splitting)
    # Re-compute line-based positions from headings
    # headings = [(level, title, pos), ...] where pos is approximate char offset

    # Build sections: for each heading, find its line index
    # We'll re-parse the text to find exact line indices of headings
    re_numbered = re.compile(r'^(#{1,4})\s+(\d+(?:\.\d+)*)\s+(.*)$')
    re_appendix_md = re.compile(r'^(#{1,4})\s+(附录[A-Z])\s*(.*)$')
    re_appendix_sub = re.compile(r'^(#{1,4})\s+([A-Z]\.\d+)\s*(.*)$')
    re_raw_numbered = re.compile(r'^(\d+(?:\.\d+)*)\s*(.{1,60})$')             # 4.1 总则 or 1范围 (no ##)
    re_raw_appendix = re.compile(r'^([A-Z]\.\d+)\s+(.{1,60})$')

    # Map each heading from profile to its line index
    # [Phase 3] O(n) 优化：先构建 lines → title 映射表，再单次遍历匹配
    # 构建 lines 索引：候选标题 → 行号
    line_candidates = {}  # candidate_title → line_idx
    for i, line in enumerate(lines):
        line_stripped = line.rstrip()

        m = re_numbered.match(line_stripped)
        if m:
            candidate_title = f"{m.group(2)} {m.group(3)}".strip()
            line_candidates[candidate_title] = i
            line_candidates[m.group(2)] = i  # section number 也能匹配

        m = re_appendix_md.match(line_stripped)
        if m:
            candidate_title = f"{m.group(2)} {m.group(3)}".strip() if m.group(3) else m.group(2)
            line_candidates[candidate_title] = i
            line_candidates[m.group(2)] = i

        m = re_appendix_sub.match(line_stripped)
        if m:
            candidate_title = f"{m.group(2)} {m.group(3)}".strip() if m.group(3) else m.group(2)
            line_candidates[candidate_title] = i
            line_candidates[m.group(2)] = i

        m = re_raw_numbered.match(line_stripped)
        if m:
            candidate_title = f"{m.group(1)} {m.group(2)}".strip()
            line_candidates[candidate_title] = i
            line_candidates[m.group(1)] = i

        m = re_raw_appendix.match(line_stripped)
        if m:
            candidate_title = f"{m.group(1)} {m.group(2)}".strip()
            line_candidates[candidate_title] = i
            line_candidates[m.group(1)] = i

    # O(n) 匹配：遍历 headings，从索引中查找
    heading_lines = []  # [(line_idx, level, section_number_tuple, title)]
    for level, title, _pos in headings:
        matched = False
        sec_num = None

        # 精确匹配
        if title in line_candidates:
            matched = True
        else:
            # 前缀匹配：title 以某个 candidate 开头
            for cand, line_idx in line_candidates.items():
                if title.startswith(cand) or cand.startswith(title):
                    matched = True
                    break

        if matched:
            # 找到最近的行号
            best_line = 0
            for cand, line_idx in line_candidates.items():
                if title.startswith(cand) or cand.startswith(title) or cand == title:
                    best_line = line_idx
                    break

            sec_num = _parse_section_number(title)
            heading_lines.append((best_line, level, sec_num, title))

    # Sort by line index
    heading_lines.sort(key=lambda x: x[0])

    # Post-process: assign synthetic sec_nums to appendix headings
    # so they group correctly (e.g., 附录A → (1000,), A.1 → (1000, 1), 附录B → (1001,))
    appendix_counter = [0]
    last_appendix_id = [None]
    re_appendix_title = re.compile(r'^附录([A-Z])')
    re_appendix_sub_title = re.compile(r'^([A-Z])\.(\d+)')
    updated_lines = []
    for line_idx, level, sec_num, title in heading_lines:
        if sec_num is None:
            m = re_appendix_title.match(title)
            if m:
                appendix_counter[0] += 1
                last_appendix_id[0] = appendix_counter[0]
                sec_num = (1000 + appendix_counter[0],)
            else:
                m = re_appendix_sub_title.match(title)
                if m and last_appendix_id[0] is not None:
                    sub_num = int(m.group(2))
                    sec_num = (1000 + last_appendix_id[0], sub_num)
        updated_lines.append((line_idx, level, sec_num, title))
    heading_lines = updated_lines

    if not heading_lines:
        return []

    # Split text into sections based on heading positions
    sections = []  # [(line_start, line_end, level, sec_num, title)]
    # Text before first heading
    if heading_lines[0][0] > 0:
        sections.append((0, heading_lines[0][0], 0, None, "前言"))

    for idx, (line_idx, level, sec_num, title) in enumerate(heading_lines):
        end_line = heading_lines[idx + 1][0] if idx + 1 < len(heading_lines) else len(lines)
        sections.append((line_idx, end_line, level, sec_num, title))

    # Extract text for each section
    section_texts = []
    for line_start, line_end, level, sec_num, title in sections:
        section_text = "\n".join(lines[line_start:line_end]).strip()
        section_texts.append({
            "text": section_text,
            "level": level,
            "sec_num": sec_num,
            "title": title,
            "line_start": line_start,
        })

    if not section_texts:
        return []

    # Determine leaf (child) and parent sections
    # Strategy: sections with deeper sec_num (more dots) are children
    # Sections with shallower sec_num are parents
    # Text before first heading (sec_num=None) is a parent-only section

    # Find the maximum depth of section numbers
    all_sec_nums = [s["sec_num"] for s in section_texts if s["sec_num"] is not None]
    if not all_sec_nums:
        return []

    max_depth = max(len(sn) for sn in all_sec_nums)

    # Classify: if max_depth >= 2, deeper sections (len > 1) are children,
    # top-level sections (len == 1 or None) are parents
    # If max_depth == 1, all sections are both child and parent

    # Build parent groups: group sections by their top-level number
    parent_groups = {}  # top_level_number -> [section_indices]
    current_top = None
    for i, s in enumerate(section_texts):
        if s["sec_num"] is not None:
            top = s["sec_num"][0]
            if top != current_top:
                current_top = top
            if current_top not in parent_groups:
                parent_groups[current_top] = []
            parent_groups[current_top].append(i)
        else:
            # Text before first heading — standalone parent
            parent_groups[None] = [i]

    # Merge small children
    for top_level, indices in parent_groups.items():
        if len(indices) <= 1:
            continue
        merged = []
        for idx in indices:
            if merged and len(section_texts[idx]["text"]) < min_child_size:
                # Merge into previous
                merged[-1] = idx
            else:
                merged.append(idx)
        parent_groups[top_level] = merged

    # Build chunks
    results = []
    child_index = 0
    parent_index = 0

    # Process sections in order
    processed_parents = set()

    for i, s in enumerate(section_texts):
        top = s["sec_num"][0] if s["sec_num"] is not None else None
        if top in processed_parents:
            continue

        if top is None:
            # Pre-heading text: standalone parent
            parent_text = s["text"]
            if not parent_text.strip():
                processed_parents.add(top)
                continue

            # This is a child under this parent
            section_hint = s["title"][:80] if s["title"] else parent_text[:80]
            # If child too small, merge into parent directly
            if len(parent_text) < min_child_size and len(section_texts) > 1:
                # Merge with next section's parent
                next_i = i + 1
                if next_i < len(section_texts):
                    next_parent_text = "\n\n".join(
                        section_texts[j]["text"] for j in parent_groups.get(
                            section_texts[next_i]["sec_num"][0] if section_texts[next_i]["sec_num"] else None, []
                        )
                    )
                    parent_text = parent_text + "\n\n" + next_parent_text[:max_parent_size]

            results.append({
                "child": _truncate_at_sentence_boundary(parent_text, 800),
                "parent": parent_text[:max_parent_size],
                "child_index": child_index,
                "parent_index": parent_index,
                "section_hint": section_hint,
            })
            child_index += 1
            parent_index += 1
            processed_parents.add(top)
            continue

        # Get all sections under this parent
        group_indices = parent_groups.get(top, [])
        if not group_indices:
            continue

        # Check if this is a leaf section (no children)
        is_leaf = max_depth == 1 or len(s["sec_num"]) == max_depth

        if is_leaf and len(group_indices) == 1:
            # Single leaf section: child = this section, parent = this section
            parent_text = s["text"]
            section_hint = s["title"][:80] if s["title"] else parent_text[:80]

            results.append({
                "child": _truncate_at_sentence_boundary(parent_text, 800),
                "parent": parent_text[:max_parent_size],
                "child_index": child_index,
                "parent_index": parent_index,
                "section_hint": section_hint,
            })
            child_index += 1
            parent_index += 1
        else:
            # Parent section with children
            all_text = "\n\n".join(section_texts[j]["text"] for j in group_indices if section_texts[j]["text"].strip())
            section_hint = s["title"][:80] if s["title"] else all_text[:80]

            # Create child chunks from individual sections
            for j in group_indices:
                child_text = section_texts[j]["text"]
                if not child_text.strip():
                    continue
                if len(child_text) < min_child_size:
                    # Try to merge with next sibling
                    next_j_idx = group_indices.index(j) + 1
                    if next_j_idx < len(group_indices):
                        next_j = group_indices[next_j_idx]
                        child_text = child_text + "\n\n" + section_texts[next_j]["text"]
                    if len(child_text) < min_child_size:
                        # Still too small, use as-is
                        pass
                # P0-4: 如果子块过大，按条款拆分
                if len(child_text) > 800:
                    clauses = _clause_split(child_text, max_child_size=800)
                    for clause in clauses:
                        results.append({
                            "child": clause["text"],
                            "parent": all_text[:max_parent_size],
                            "child_index": child_index,
                            "parent_index": parent_index,
                            "section_hint": section_hint,
                        })
                        child_index += 1
                else:
                    results.append({
                        "child": _truncate_at_sentence_boundary(child_text, 800),
                        "parent": all_text[:max_parent_size],
                        "child_index": child_index,
                        "parent_index": parent_index,
                        "section_hint": section_hint,
                    })
                    child_index += 1

            parent_index += 1

        processed_parents.add(top)

    return results


def _heading_chunk_regulation(text: str, headings: list) -> list:
    """Heading-based chunking for regulation documents (article-based)."""
    lines = text.split("\n")
    re_article = re.compile(r'^(第[一二三四五六七八九十百千零\d]+条)')

    # Find article line indices
    article_lines = []
    for level, title, _pos in headings:
        for i, line in enumerate(lines):
            if re.match(r'^' + re.escape(title[:5]).replace(r'\ ', ' ') , line.strip()):
                article_lines.append((i, title))
                break
        else:
            # Fallback: find by article number pattern
            for i, line in enumerate(lines):
                if re_article.match(line.strip()):
                    article_lines.append((i, title))
                    break

    if not article_lines:
        return []

    # Sort by line index
    article_lines.sort(key=lambda x: x[0])

    # Split into article texts
    article_texts = []
    for idx, (line_idx, title) in enumerate(article_lines):
        end_line = article_lines[idx + 1][0] if idx + 1 < len(article_lines) else len(lines)
        article_text = "\n".join(lines[line_idx:end_line]).strip()
        article_texts.append({"text": article_text, "title": title})

    if not article_texts:
        return []

    # child = each article, parent = group of 3-5 articles
    results = []
    child_index = 0
    parent_index = 0
    group_size = 4  # articles per parent group

    for i in range(0, len(article_texts), group_size):
        group = article_texts[i:i + group_size]
        parent_text = "\n\n".join(a["text"] for a in group)
        section_hint = group[0]["title"][:80]

        for a in group:
            results.append({
                "child": a["text"][:800],
                "parent": parent_text,
                "child_index": child_index,
                "parent_index": parent_index,
                "section_hint": section_hint,
            })
            child_index += 1
            parent_index += 1

    return results


def extract_table_chunks(text: str) -> list:
    """检测并提取Markdown表格和HTML表格为独立chunks。

    返回 [{"child": str, "parent": str, "child_index": int, "parent_index": int, "section_hint": str}]

    parent 字段包含表格前后的文字上下文，避免表格孤立。
    """
    results = []
    lines = text.split("\n")

    def _get_surrounding_context(line_idx: int) -> str:
        """获取表格前后的文字上下文（各最近2行非表格文字）"""
        before = []
        for i in range(max(0, line_idx - 5), line_idx):
            if lines[i].strip() and not re.match(r'^\s*\|', lines[i]):
                before.append(lines[i].strip())
        after = []
        for i in range(line_idx + 1, min(len(lines), line_idx + 6)):
            if lines[i].strip() and not re.match(r'^\s*\|', lines[i]):
                after.append(lines[i].strip())
        ctx_parts = []
        if before:
            ctx_parts.append("… " + " ".join(before[-2:]))
        if after:
            ctx_parts.append(" ".join(after[:2]) + " …")
        return " | ".join(ctx_parts) if ctx_parts else ""

    # ── 1. HTML表格检测: <table>...</table> ──
    re_html_table = re.compile(r'<table>.*?</table>', re.DOTALL)
    for m in re_html_table.finditer(text):
        table_text = m.group(0)
        re_first_row = re.compile(r'<td[^>]*>(.*?)</td>')
        first_cells = re_first_row.findall(table_text[:500])
        hint = " | ".join(c[:20] for c in first_cells[:3]) if first_cells else table_text[:80]
        table_pos = text.find(table_text[:50])
        surrounding = _get_surrounding_context(text[:table_pos].count("\n")) if table_pos >= 0 else ""
        results.append({
            "child": table_text,
            "parent": f"{surrounding}\n\n{table_text}" if surrounding else table_text,
            "child_index": 0,
            "parent_index": 0,
            "section_hint": f"[HTML表格] {hint}"
        })

    # ── 2. Markdown表格检测: |...|格式 ──
    table_start = None
    table_lines = []

    re_table_row = re.compile(r'^\s*\|.+\|\s*$')
    re_table_sep = re.compile(r'^\s*\|[\s\-:|]+\|\s*$')

    for i, line in enumerate(lines):
        # 跳过已被HTML表格检测覆盖的行
        is_row = bool(re_table_row.match(line))
        is_sep = bool(re_table_sep.match(line))

        if is_row or is_sep:
            if table_start is None:
                table_start = i
                table_lines = [line]
            else:
                table_lines.append(line)
        else:
            if table_start is not None and len(table_lines) >= 3:
                table_text = "\n".join(table_lines)
                if any(re_table_sep.match(l) for l in table_lines):
                    surrounding = _get_surrounding_context(table_start)
                    results.append({
                        "child": table_text,
                        "parent": f"{surrounding}\n\n{table_text}" if surrounding else table_text,
                        "child_index": 0,
                        "parent_index": table_start,
                        "section_hint": f"[表格] {table_lines[0][:80]}"
                    })
            table_start = None
            table_lines = []

    # 处理文件末尾的Markdown表格
    if table_start is not None and len(table_lines) >= 3:
        if any(re_table_sep.match(l) for l in table_lines):
            table_text = "\n".join(table_lines)
            surrounding = _get_surrounding_context(table_start)
            results.append({
                "child": table_text,
                "parent": f"{surrounding}\n\n{table_text}" if surrounding else table_text,
                "child_index": 0,
                "parent_index": table_start,
                "section_hint": f"[表格] {table_lines[0][:80]}"
            })

    return results


def excel_row_chunk(text: str, doc_title: str = "") -> list:
    """Excel 检查表专用分块：每个检查项（空行分隔）独立成chunk。

    输入 text 是 parse_document() 已输出的结构化文本，格式：
      [Sheet: Sheet1]
      第1项 - 调查类
      检查项: xxx
      检查要求: xxx
      检查方法: xxx

      第2项 - 方案类
      ...

    每个检查项以 "第N项" 开头，到下一个 "第N项" 或空行结束。
    """
    import re as _re
    lines = text.split("\n")
    chunks = []
    current_lines = []
    current_header = ""

    for line in lines:
        # 检测新检查项的开始：第N项 或 第N项-类别
        if _re.match(r'^第\d+项', line.strip()):
            # 保存上一个检查项
            if current_lines:
                child = "\n".join(current_lines).strip()
                if child:
                    chunks.append({
                        "child": child,
                        "parent": child,
                        "child_index": len(chunks),
                        "parent_index": len(chunks),
                        "section_hint": f"[{doc_title}] {current_header}" if doc_title else current_header,
                    })
            current_lines = [line]
            current_header = line.strip()[:80]
        elif line.strip().startswith("[Sheet:"):
            # Sheet标题行，作为上下文前缀保留
            current_lines.append(line)
        elif line.strip() == "":
            # 空行：如果当前有内容，保存为独立chunk
            if current_lines:
                child = "\n".join(current_lines).strip()
                if child:
                    chunks.append({
                        "child": child,
                        "parent": child,
                        "child_index": len(chunks),
                        "parent_index": len(chunks),
                        "section_hint": f"[{doc_title}] {current_header}" if doc_title else current_header,
                    })
                current_lines = []
                current_header = ""
        else:
            current_lines.append(line)

    # 最后一个检查项
    if current_lines:
        child = "\n".join(current_lines).strip()
        if child:
            chunks.append({
                "child": child,
                "parent": child,
                "child_index": len(chunks),
                "parent_index": len(chunks),
                "section_hint": f"[{doc_title}] {current_header}" if doc_title else current_header,
            })

    return chunks


def parent_child_chunk(text: str, child_size: int = 384, parent_size: int = 2048, overlap: int = 80, doc_title: str = "") -> list:
    """将文本切分为父子分块。

    Args:
        text: 待切分的文本
        child_size: 子块大小（用于向量匹配）
        parent_size: 父块大小（用于 LLM 上下文）
        overlap: 子块滑动窗口重叠
        doc_title: 文档标题，作为 section_hint（CC 评审决策 4-A）。
                   未提供时回退到 parent_text[:80]（保持兼容）。

    返回 list of dict:
    [
        {
            "child": "子块文本（用于向量匹配）",
            "parent": "父块文本（用于LLM上下文）",
            "child_index": 0,
            "parent_index": 0,
            "section_hint": "doc_title 若提供，否则父块前80字符"
        },
        ...
    ]
    """
    # Step 1: 按段落分割
    paragraphs = text.split("\n\n")
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    # Step 2: 聚合段落为父块（按 parent_size 滑动窗口）
    parents = []
    p_idx = 0
    while p_idx < len(paragraphs):
        parent_text = ""
        while p_idx < len(paragraphs):
            candidate = (parent_text + "\n\n" + paragraphs[p_idx]).strip() if parent_text else paragraphs[p_idx]
            if len(candidate) > parent_size and parent_text:
                break
            parent_text = candidate
            p_idx += 1
        if parent_text:
            parents.append(parent_text)

    # Step 3: 在每个父块内切子块
    results = []
    child_index = 0
    for p_idx, parent_text in enumerate(parents):
        # CC 评审决策 4-A: doc_title 若提供则用文档标题，否则回退到父段落前 80 字符
        section_hint = doc_title.strip() if doc_title.strip() else parent_text[:80]
        # 按 child_size 滑动窗口切子块（子块可以跨段落边界）
        pos = 0
        while pos < len(parent_text):
            end = min(pos + child_size, len(parent_text))
            # 在目标位置附近找最近的句子边界（中文：。！？；\n，英文：.!?）
            if end < len(parent_text):
                # 在 child_size ±20% 范围内找最近的句子结束符
                search_start = max(pos + int(child_size * 0.8), pos + 1)
                search_end = min(pos + int(child_size * 1.2), len(parent_text))
                best_break = end
                for boundary_char in ['\n', '。', '！', '？', '；', '.', '!', '?']:
                    idx = parent_text.rfind(boundary_char, search_start, search_end)
                    if idx > 0:
                        best_break = idx + 1
                        break
                end = best_break
            child_text = parent_text[pos:end]
            if child_text.strip():
                results.append({
                    "child": child_text,
                    "parent": parent_text,
                    "child_index": child_index,
                    "parent_index": p_idx,
                    "section_hint": section_hint,
                })
                child_index += 1
            pos += child_size - overlap  # 带重叠的滑动窗口
            if pos >= len(parent_text):
                break

    return results


# ─── Helpers ──────────────────────────────────────────────────────────


def _dicts_to_chunks(dicts: list) -> List[Chunk]:
    """Convert internal dict format to Chunk dataclass list."""
    chunks = []
    for d in dicts:
        chunks.append(Chunk(
            text=d["child"],
            index=d["child_index"],
            heading=d.get("section_hint", ""),
            parent_idx=d.get("parent_index"),
            metadata={
                "parent": d.get("parent", ""),
                "section_hint": d.get("section_hint", ""),
            },
        ))
    return chunks


# ─── Strategy classes ──────────────────────────────────────────────────


class ChunkingStrategy:
    """Base class for chunking strategies."""

    def chunk(self, text: str, filename: str = "", **kwargs) -> List[Chunk]:
        raise NotImplementedError


class HeadingChunking(ChunkingStrategy):
    """Split by document headings (## / ### / 一、二、三)."""

    def chunk(self, text: str, filename: str = "", **kwargs) -> List[Chunk]:
        from app.services.quality import profile_document  # avoid circular import
        min_child_size = kwargs.get("min_child_size", 200)
        max_parent_size = kwargs.get("max_parent_size", 3000)
        doc_title = kwargs.get("doc_title", filename)

        profile = profile_document(text)
        dict_results = heading_chunk(text, profile, min_child_size, max_parent_size)

        if not dict_results:
            # Fall back to parent_child_chunk
            child_size = kwargs.get("child_size", settings.default_chunk_size)
            parent_size = kwargs.get("parent_size", child_size * 4)
            overlap = kwargs.get("overlap", settings.chunk_overlap)
            dict_results = parent_child_chunk(text, child_size, parent_size, overlap, doc_title=doc_title)

        # Extract table chunks
        table_dicts = extract_table_chunks(text)
        for td in table_dicts:
            td["child_index"] = len(dict_results)
            td["parent_index"] = len(dict_results)

        all_dicts = dict_results + table_dicts
        return _dicts_to_chunks(all_dicts)


class ParentChildChunking(ChunkingStrategy):
    """Parent-child chunking with overlap for long sections."""

    def chunk(self, text: str, filename: str = "", **kwargs) -> List[Chunk]:
        child_size = kwargs.get("child_size", settings.default_chunk_size)
        parent_size = kwargs.get("parent_size", child_size * 4)
        overlap = kwargs.get("overlap", settings.chunk_overlap)
        doc_title = kwargs.get("doc_title", filename)

        dict_results = parent_child_chunk(text, child_size, parent_size, overlap, doc_title=doc_title)

        # Extract table chunks
        table_dicts = extract_table_chunks(text)
        for td in table_dicts:
            td["child_index"] = len(dict_results)
            td["parent_index"] = len(dict_results)

        all_dicts = dict_results + table_dicts
        return _dicts_to_chunks(all_dicts)


class ExcelRowChunking(ChunkingStrategy):
    """Excel-specific: each row = one chunk with column headers as context."""

    def chunk(self, text: str, filename: str = "", **kwargs) -> List[Chunk]:
        doc_title = kwargs.get("doc_title", filename)
        dict_results = excel_row_chunk(text, doc_title)

        if not dict_results:
            # Fall back to parent_child_chunk
            child_size = kwargs.get("child_size", settings.default_chunk_size)
            parent_size = kwargs.get("parent_size", child_size * 4)
            overlap = kwargs.get("overlap", settings.chunk_overlap)
            dict_results = parent_child_chunk(text, child_size, parent_size, overlap, doc_title=doc_title)

        return _dicts_to_chunks(dict_results)


def select_strategy(filename: str, text: str) -> ChunkingStrategy:
    """Auto-select the best chunking strategy based on document type.

    NOTE (2026-06-19): 仅基于 filename 后缀分流，不调用 profile_document。
    实际 upload.py / documents.py pipeline 不使用此函数 —— 它们直接调用
    `_heading_chunk_gb` / `parent_child_chunk` / `excel_row_chunk`，dispatch
    由 profile_document() 完成。本函数仅供未来批处理工具或外部 caller 使用，
    保持轻量化（只看后缀），与主 pipeline 故意保持解耦。
    """
    if filename.endswith((".xlsx", ".xls")):
        return ExcelRowChunking()
    # Default: heading-based with parent-child fallback
    return HeadingChunking()
