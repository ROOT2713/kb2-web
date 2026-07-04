#!/usr/bin/env python3
"""
Phase 1b: Extract section_type and section_header from parent_text.
Detects: 第N条 (articles), 第N章 (chapters), 附录X (appendices), 附件X (attachments),
table content, summary/front-matter, and other structural markers.
"""
import re
import sqlite3
import sys

DB = "/home/ubuntu/kb-web/data/kb.db"
DRY_RUN = "--dry-run" in sys.argv

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. Check if columns already exist
c.execute("PRAGMA table_info(parent_chunks)")
cols = [col['name'] for col in c.fetchall()]
has_section_type = 'section_type' in cols
has_section_header = 'section_header' in cols

if not has_section_type or not has_section_header:
    print(f"Columns section_type={has_section_type}, section_header={has_section_header}")
    print("Running ALTER TABLE to add missing columns...")
    if not DRY_RUN:
        if not has_section_type:
            c.execute("ALTER TABLE parent_chunks ADD COLUMN section_type TEXT")
        if not has_section_header:
            c.execute("ALTER TABLE parent_chunks ADD COLUMN section_header TEXT")
        conn.commit()
        print("  Added columns successfully.")
    else:
        print("  [DRY RUN] Would add columns.")

c.execute("SELECT COUNT(*) FROM parent_chunks")
total_chunks = c.fetchone()[0]
print(f"\nTotal parent_chunks: {total_chunks}")


def detect_section(text: str) -> tuple[str, str]:
    """
    Detect section type and extract header from parent_text.
    Returns (section_type, section_header).
    """
    if not text:
        return ("unknown", "")

    # Clean and take first ~200 chars for detection
    first_200 = text.strip()[:200]

    # --- Pattern 1: 附录 (Appendix) ---
    m = re.search(r'(附录\s*[A-Z一二三四五六七八九十\d]+[^\n]{0,40})', first_200)
    if m:
        return ("appendix", m.group(1).strip())

    # --- Pattern 2: 附件 (Attachment) ---
    m = re.search(r'(附件\s*[A-Z一二三四五六七八九十\d]+[^\n]{0,40})', first_200)
    if m:
        return ("appendix", m.group(1).strip())

    # --- Pattern 3: 第N条 (Article) ---
    m = re.search(r'(第[一二三四五六七八九十百\d]+条[^\n]{0,40})', first_200)
    if m:
        return ("article", m.group(1).strip())

    # --- Pattern 4: 第N章 (Chapter) ---
    m = re.search(r'(第[一二三四五六七八九十百\d]+章[^\n]{0,60})', first_200)
    if m:
        return ("chapter", m.group(1).strip())

    # --- Pattern 5: Table-like content (contains 表X, 表格, or table structure) ---
    m = re.search(r'(表\s*[A-Z\d]+[^\n]{0,40})', first_200)
    if m:
        return ("table", m.group(1).strip())

    # --- Pattern 6: X.X.X numbered section heading (e.g., "3.1 一般规定") ---
    m = re.match(r'\s*(\d+(?:\.\d+)*\s+[^\n]{2,60})', first_200)
    if m:
        return ("body", m.group(1).strip())

    # --- Pattern 7: 前言 / 总则 / 范围 / 术语 (front matter) ---
    m = re.search(r'^\s*(前\s*言|总\s*则|范\s*围|术语|规范性引用文件|引\s*言)', first_200)
    if m:
        return ("summary", m.group(1).strip())

    # --- Pattern 8: Starts with section/chapter-like Chinese patterns ---
    m = re.search(r'^\s*(第[一二三四五六七八九十百\d]+[节部分篇])', first_200)
    if m:
        return ("body", m.group(1).strip())

    # --- Pattern 9: First line looks like a heading (short, no punctuation) ---
    first_line = text.strip().split('\n')[0].strip()
    if 2 <= len(first_line) <= 60 and not re.search(r'[，。；：？、]', first_line):
        # Check it's not just a fragment
        if re.search(r'[\u4e00-\u9fff]', first_line) or first_line.isascii():
            return ("body", first_line)

    # --- Pattern 10: Document header / metadata block ---
    first_words = first_200[:20]
    if re.match(r'^(ICS|备案号|中华人民共和国|DB|Q/|[A-Z]{2,10}\s)', first_words):
        return ("summary", first_words.strip())

    return ("body", "")


# 2. Process all chunks — GROUP BY doc first for structured docs
c.execute("""
    SELECT pc.doc_id, pc.parent_idx, pc.parent_text, d.doc_type
    FROM parent_chunks pc
    JOIN documents d ON pc.doc_id = d.doc_id
    WHERE d.status = 'active'
    ORDER BY pc.doc_id, pc.parent_idx
""")
rows = c.fetchall()

if DRY_RUN:
    print("\n=== EXTRACTION PREVIEW (first 30 chunks) ===")
    prev_doc = None
    for r in rows[:30]:
        doc_id, idx, text, doc_type = r['doc_id'], r['parent_idx'], str(r['parent_text']), r['doc_type']
        section_type, section_header = detect_section(text)
        
        if doc_id != prev_doc:
            print(f"\n--- doc_id={doc_id[:12]}... ({doc_type}) ---")
            prev_doc = doc_id
        print(f"  [{idx:>2}] {section_type:<10} | {section_header[:40]:40} | {text[:50]}...")
else:
    # Check if columns exist first
    if not has_section_type or not has_section_header:
        print("\nERROR: Columns don't exist yet. Run SQL migration first.")
        sys.exit(1)

    updated = 0
    errors = 0
    types_dist: dict[str, int] = {}
    
    for r in rows:
        doc_id, idx, text, doc_type = r['doc_id'], r['parent_idx'], str(r['parent_text']), r['doc_type']
        section_type, section_header = detect_section(text)
        
        try:
            c.execute(
                "UPDATE parent_chunks SET section_type = ?, section_header = ? WHERE doc_id = ? AND parent_idx = ?",
                (section_type, section_header[:200], doc_id, idx)
            )
            updated += 1
            types_dist[section_type] = types_dist.get(section_type, 0) + 1
        except Exception as e:
            errors += 1
    
    conn.commit()
    
    print(f"\nUpdated {updated} chunks with section_type/section_header")
    print(f"Errors: {errors}")
    
    print("\n=== SECTION TYPE DISTRIBUTION ===")
    for t, count in sorted(types_dist.items(), key=lambda x: -x[1]):
        print(f"  {t:<12}: {count:>5} ({count/updated*100:.1f}%)" if updated else f"  {t:<12}: {count:>5}")
    
    # 3. Verify
    c.execute("SELECT COUNT(*) FROM parent_chunks WHERE section_type IS NOT NULL")
    filled = c.fetchone()[0]
    print(f"\n=== VERIFICATION ===")
    print(f"Total parent_chunks with section_type: {filled}")
    
    c.execute("SELECT section_type, COUNT(*) as cnt FROM parent_chunks WHERE section_type IS NOT NULL GROUP BY section_type ORDER BY cnt DESC")
    print("\nBy section_type:")
    for r in c.fetchall():
        print(f"  {r['section_type']:<12}: {r['cnt']}")
    
    # Docs counts with sections
    c.execute("""
        SELECT COUNT(DISTINCT doc_id) FROM parent_chunks 
        WHERE section_type IN ('article', 'chapter', 'appendix')
    """)
    print(f"\nDocs with article/chapter/appendix sections: {c.fetchone()[0]}")

conn.close()
print("\nDone.")
