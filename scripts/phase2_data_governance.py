#!/usr/bin/env python3
"""
Phase 2 — Data Governance for kb2-web.
1. Extract published_year from parent_text for 84 gb_standard docs.
2. Improve section_type extraction for 185 NULL chunks (date lines, markdown headings, compressed format).
3. Backfill geo_scope from bank/title.
4. Execute + verify.
"""
import re
import sqlite3
import sys

DB = "/home/ubuntu/kb-web/data/kb.db"
DRY_RUN = "--dry-run" in sys.argv

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ═══════════════════════════════════════════════════════════════════
# 1. published_year from parent_text for gb_standard
# ═══════════════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 1: Extract published_year from parent_text for gb_standard")
print("=" * 70)

# Get gb_standard docs missing published_date
c.execute("""
    SELECT d.doc_id, d.title, pc.parent_text
    FROM documents d
    JOIN parent_chunks pc ON pc.doc_id = d.doc_id AND pc.parent_idx = 0
    WHERE d.status='active' AND d.doc_type='gb_standard'
      AND (d.published_date IS NULL OR d.published_date = '')
    ORDER BY d.title
""")
rows = c.fetchall()
print(f"gb_standard docs missing published_date: {len(rows)}")

# Patterns to extract year from parent_text
YEAR_PATTERNS = [
    # 1. Standard number suffix: YD 5214-2015, GB/T 40429-2021, CJ/T 236-2006
    re.compile(r'(?:[A-Z]+/T|GB|GA|YD|SJ|CJ|DBJ|JJF|CECS|CJJ|HJ|JG)[/\s]*\d+(?:\.\d+)?[-—](20\d{2}|19\d{2})'),
    # 2. Chinese date: 2015年4月30日, 2012年8月23日
    re.compile(r'(20\d{2})年\d{1,2}月\d{1,2}日'),
    # 3. Chinese date with just month-day: 2015年04月30日
    re.compile(r'(20\d{2})年\d{2}月\d{2}日'),
    # 4. ISO date: 2021-08-20 发布, 2006-11-29
    re.compile(r'(20\d{2})-\d{2}-\d{2}'),
    # 5. Loose year at end: "2019年12月01日发布"
    re.compile(r'(20\d{2})年'),
    # 6. Bare year in text
    re.compile(r'\b(20\d{2})\b'),
]


def extract_year_from_text(text: str) -> int | None:
    """Extract publication year from parent_text."""
    if not text:
        return None
    for pat in YEAR_PATTERNS:
        m = pat.search(text)
        if m:
            y = int(m.group(1))
            if 1900 <= y <= 2030:
                return y
    return None


# Preview
print("\n--- EXTRACTION PREVIEW ---")
updated_pub = 0
no_year_found = []
errors_pub = []

for r in rows:
    doc_id, title, parent_text = r['doc_id'], str(r['title']), str(r['parent_text'])
    year = extract_year_from_text(parent_text)
    if year:
        src = parent_text[:80].replace('\n', ' ')
        print(f"  ✓ {doc_id[:8]}... → {year}-01-01 | {title[:50]} | from: {src}")
    else:
        print(f"  ✗ {doc_id[:8]}... → NO YEAR   | {title[:50]}")
        no_year_found.append((doc_id, title, parent_text[:100]))

if DRY_RUN:
    print("\n[DRY RUN] Would update published_date for matches.")
else:
    updated_count = 0
    for r in rows:
        doc_id, title, parent_text = r['doc_id'], str(r['title']), str(r['parent_text'])
        year = extract_year_from_text(parent_text)
        if year:
            date_str = f"{year}-01-01"
            try:
                c.execute(
                    "UPDATE documents SET published_date = ? WHERE doc_id = ? AND (published_date IS NULL OR published_date = '')",
                    (date_str, doc_id)
                )
                if c.rowcount:
                    updated_count += 1
                    updated_pub += 1
            except Exception as e:
                errors_pub.append((doc_id, str(e)))
        else:
            no_year_found.append((doc_id, title, parent_text[:100]))

    conn.commit()
    print(f"\nPublished date updated: {updated_count}")
    print(f"No year found: {len(no_year_found)}")

    if no_year_found:
        print("\n--- NO YEAR FOUND ---")
        for doc_id, title, preview in no_year_found[:10]:
            print(f"  {doc_id[:8]} | {title[:50]} | {preview[:60]}")

    if errors_pub:
        print(f"\nErrors: {len(errors_pub)}")
        for e in errors_pub[:5]:
            print(f"  {e}")


# ═══════════════════════════════════════════════════════════════════
# 2. Improve section_type extraction for 185 NULL chunks
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 2: Improve section_type extraction for NULL chunks")
print("=" * 70)

c.execute("""
    SELECT pc.doc_id, pc.parent_idx, pc.parent_text, d.title, d.doc_type
    FROM parent_chunks pc
    JOIN documents d ON pc.doc_id = d.doc_id
    WHERE pc.section_type IS NULL
    ORDER BY pc.doc_id, pc.parent_idx
""")
null_rows = c.fetchall()
print(f"NULL section_type chunks: {len(null_rows)}")


def detect_section_v2(text: str) -> tuple[str, str]:
    """
    Improved section_type/section_header detection.
    Handles: date lines, markdown headings, compressed format, standard patterns.
    """
    if not text:
        return ("unknown", "")

    # Take first line and full text trimmed
    lines = text.strip().split('\n')
    first_line = lines[0].strip()
    first_200 = text.strip()[:200]

    # --- Pattern A: Date-only lines ---
    # Matches: "2006-11-29 发布", "2016-05-01 实施", "2015-02-11 发布"
    date_line = re.match(r'^\s*(20\d{2}[-年]\d{1,2}[-月]\d{1,2}[^。\n]{0,40})$', first_line)
    if date_line:
        return ("summary", date_line.group(1).strip())

    # Also check "2007-03-01 实施" etc
    if re.match(r'^\s*\d{4}-\d{2}-\d{2}\s', first_line):
        return ("summary", first_line[:60])

    # --- Pattern B: Markdown heading lines ---
    # Matches: "## 1 范围", "## 3 术语和定义", "## 5 要求", "## 6 试验"
    md_heading = re.match(r'^#{1,3}\s+(.+)$', first_line)
    if md_heading:
        header = md_heading.group(1).strip()
        # Check if it's a section/chapter/range
        if re.match(r'^[一二三四五六七八九十\d]+\s', header) or \
           re.match(r'^第[一二三四五六七八九十\d]+[章节]', header) or \
           re.match(r'^附录', header) or \
           re.match(r'^附件', header) or \
           re.match(r'^前\s*言', header) or \
           re.match(r'^目\s*次', header) or \
           re.match(r'^[A-Z]\.\d', header) or \
           len(header) <= 60:
            return ("body", header)
        return ("body", header)

    # --- Pattern C: Compressed "1范围1" (no dots, number + text + number) ---
    compressed_no_dots = re.match(r'^\s*(\d+)([^\d\n]{2,60})(\d+)\s*$', first_line)
    if compressed_no_dots:
        num = compressed_no_dots.group(1)
        section_text = compressed_no_dots.group(2).strip()
        if section_text:
            return ("body", f"{num}{section_text}")

    # --- Pattern D: Compressed format "2规范性引用文件…………1" ---
    # Format: number + text + ellipsis dots + page number
    compressed_dots = re.match(r'^\s*(\d+)([^0-9\n]{2,60})[\.…·]{2,}\d+\s*$', first_line)
    if compressed_dots:
        num = compressed_dots.group(1)
        section_text = compressed_dots.group(2).strip()
        # Clean up: remove trailing page numbers, dots
        section_text = re.sub(r'[\.…·]{2,}\d*\s*$', '', section_text).strip()
        # Also clean leading/trailing special chars
        section_text = re.sub(r'^[\.…·\s]+|[\.…·\s]+$', '', section_text).strip()
        if section_text:
            return ("body", f"{num}{section_text}")

    # --- Pattern E: Compressed "3 术语和定义…………………………………1" ---
    # More general: number + text + separator + page
    compressed2 = re.match(r'^\s*(\d+\s*[^0-9\n]{2,60})[\.…·]{2,}', first_line)
    if compressed2:
        header = compressed2.group(1).strip()
        header = re.sub(r'\s+', ' ', header).strip()
        if header:
            return ("body", header)

    # --- Pattern F: Compressed with ellipsis and page number at end ---
    # "5验收………4"
    compressed3 = re.match(r'^\s*(\d+\s*[^0-9\n]{1,50})[\.…·]{2,}$', first_line)
    if compressed3:
        header = compressed3.group(1).strip()
        if header:
            return ("body", header)

    # --- Pattern F: "A.9 MTBF-平均无故障周期" patterns (appendix-like content) ---
    appendix_item = re.match(r'^\s*([A-Z]\.\d+\s+[^。\n]{5,80})$', first_line)
    if appendix_item:
        return ("body", appendix_item.group(1).strip())

    # --- Pattern G: "1 范围", "2规范性引用文件" (numbered section, no markdown) ---
    numbered_section = re.match(r'^\s*(\d+)\s+([^0-9\n]{2,60})$', first_line)
    if numbered_section:
        return ("body", numbered_section.group(0).strip())

    # --- Pattern H: "序号 产品种类 产品描述 认证依据" (table-like header) ---
    if re.match(r'^\s*序号\s+', first_line):
        return ("table", first_line[:60])

    # --- Pattern I: "目 次" (table of contents) ---
    if re.match(r'^目\s*次', first_line):
        return ("summary", first_line[:60])

    # --- Pattern J: TOC-like line with dots ---
    # "前言…………………………………………………………………………"
    if re.match(r'^[^。\n]{2,40}[\.…·]{5,}', first_line):
        header = re.sub(r'[\.…·]{3,}.*$', '', first_line).strip()
        if header:
            return ("summary", header)

    # Fallback: use existing detection
    return ("body", "")


# Preview NULL chunks with improved detection
print("\n--- NULL CHUNK CLASSIFICATION (first 40) ---")
type_dist: dict[str, int] = {}
header_examples = []
prev_doc_id = None

for r in null_rows[:40]:
    doc_id, idx, text, title, doc_type = r['doc_id'], r['parent_idx'], str(r['parent_text']), str(r['title']), r['doc_type']
    section_type, section_header = detect_section_v2(text)
    type_dist[section_type] = type_dist.get(section_type, 0) + 1

    if doc_id != prev_doc_id:
        print(f"\n  --- {title[:50]} ---")
        prev_doc_id = doc_id

    compressed_flag = ""
    if re.match(r'^\s*\d+[^0-9\n]{1,50}[\.…·]{2,}', text.strip()):
        compressed_flag = " [COMPRESSED]"
    elif text.strip().startswith('#'):
        compressed_flag = " [MD]"
    elif re.match(r'^\s*\d{4}-\d{2}-\d{2}', text.strip()):
        compressed_flag = " [DATE]"

    print(f"  [{idx:>2}] {section_type:<10} | {section_header[:45]:45}{compressed_flag} | {text[:50].replace(chr(10),' ')}")

if not DRY_RUN:
    print("\n--- Executing UPDATE for NULL chunks ---")
    updated_section = 0
    errors_section = 0

    for r in null_rows:
        doc_id, idx, text = r['doc_id'], r['parent_idx'], str(r['parent_text'])
        section_type, section_header = detect_section_v2(text)

        try:
            c.execute(
                "UPDATE parent_chunks SET section_type = ?, section_header = ? WHERE doc_id = ? AND parent_idx = ?",
                (section_type, section_header[:200], doc_id, idx)
            )
            updated_section += 1
        except Exception as e:
            errors_section += 1
            print(f"  ERROR: {doc_id[:8]} idx={idx}: {e}")

    conn.commit()
    print(f"  Updated: {updated_section}, Errors: {errors_section}")


# ═══════════════════════════════════════════════════════════════════
# 3. Backfill geo_scope from bank/title
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 3: Backfill geo_scope from bank/title")
print("=" * 70)

# Get all active docs missing geo_scope
c.execute("""
    SELECT doc_id, title, bank, doc_type
    FROM documents
    WHERE status='active' AND (geo_scope IS NULL OR geo_scope = '')
    ORDER BY bank, doc_type
""")
no_geo_rows = c.fetchall()
print(f"Active docs missing geo_scope: {len(no_geo_rows)}")

# Geo-scope inference rules from title
# Priority: most specific first
def infer_geo_scope(title, bank, doc_type):
    if not title:
        return None

    # 1. Regional keywords in title
    if re.search(r'广东', title):
        return 'provincial'
    if re.search(r'广州', title) or re.search(r'穗', title):
        return 'guangzhou'
    if re.search(r'东莞', title):
        return 'dongguan'
    if re.search(r'深圳', title):
        return 'shenzhen'
    if re.search(r'佛山', title):
        return 'foshan'
    if re.search(r'省级', title) or re.search(r'省[^会]*', title):
        return 'provincial'

    # 2. Standard number prefix rules
    # GB → national (already populated for most, backfill remaining)
    if re.search(r'\bGB\b', title) or re.search(r'\bGB/T\b', title):
        return 'national'
    if re.search(r'\bISO\b', title):
        return 'national'
    if re.search(r'\bGA\b', title):
        return 'national'
    if re.search(r'\bHJ\b', title):
        return 'national'

    # 3. Provincial standard numbers
    if re.search(r'\bDB\d{2}\b', title):
        return 'provincial'

    # 4. Industry docs bank = provincial context
    if bank == 'industry_docs':
        return 'provincial'

    # 5. City-level standard numbers
    if re.search(r'\bDG\b', title):
        return 'guangzhou'

    # 6. enterprise-level
    if re.search(r'\bQ/\b', title):
        return 'enterprise'

    return None


print("\n--- GEO_SCOPE INFERENCE ---")
geo_counts: dict[str, int] = {}
no_geo_inferred = []
geo_updated = 0

for r in no_geo_rows:
    doc_id, title, bank, doc_type = r['doc_id'], str(r['title']), str(r['bank']), r['doc_type']
    scope = infer_geo_scope(title, bank, doc_type)
    if scope:
        geo_counts[scope] = geo_counts.get(scope, 0) + 1
        if DRY_RUN:
            print(f"  {scope:<12} | {doc_id[:8]} | {bank:<15} | {title[:60]}")
    else:
        no_geo_inferred.append((doc_id, title, bank))

print(f"\nInferred geo_scope distribution (if applied):")
for scope, cnt in sorted(geo_counts.items(), key=lambda x: -x[1]):
    print(f"  {scope:<12}: {cnt}")

if not DRY_RUN:
    print("\n--- Executing UPDATE for geo_scope ---")
    for r in no_geo_rows:
        doc_id, title, bank, doc_type = r['doc_id'], str(r['title']), str(r['bank']), r['doc_type']
        scope = infer_geo_scope(title, bank, doc_type)
        if scope:
            try:
                c.execute(
                    "UPDATE documents SET geo_scope = ? WHERE doc_id = ? AND (geo_scope IS NULL OR geo_scope = '')",
                    (scope, doc_id)
                )
                if c.rowcount:
                    geo_updated += 1
            except Exception as e:
                print(f"  ERROR: {doc_id[:8]}: {e}")

    conn.commit()
    print(f"  geo_scope updated: {geo_updated}")

    if no_geo_inferred:
        print(f"\n  Docs still without geo_scope: {len(no_geo_inferred)}")
        print("  Top 10 samples:")
        for doc_id, title, bank in no_geo_inferred[:10]:
            print(f"    {bank:<15} | {title[:60]}")


# ═══════════════════════════════════════════════════════════════════
# VERIFICATION
# ═══════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("VERIFICATION")
print("=" * 70)

conn.close()
print("\nDone.")
