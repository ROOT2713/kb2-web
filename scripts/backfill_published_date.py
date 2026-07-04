#!/usr/bin/env python3
"""
Phase 1a: Backfill published_date from title year regex.
Extracts 4-digit years from document titles and sets published_date = YYYY-01-01.
Priority order: standard number suffix > bracket notation > standalone year in title.
"""
import re
import sqlite3
import sys

DB = "/home/ubuntu/kb-web/data/kb.db"
DRY_RUN = "--dry-run" in sys.argv

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Get all active docs missing published_date
c.execute("""
    SELECT doc_id, title, doc_type
    FROM documents
    WHERE status='active' AND (published_date IS NULL OR published_date = '')
    ORDER BY doc_type, doc_id
""")
rows = c.fetchall()
print(f"Total active docs missing published_date: {len(rows)}")

# Track results
updates = []
no_year = []
errors = []

def extract_year(title: str, doc_type: str) -> int | None:
    """Extract publication year from title using multiple strategies."""
    if not title:
        return None

    # Strategy 1: Standard suffix pattern — "GB/T 12345-2020", "GB 50371-2006", "GB∕T 32420-2015"
    # Look for digits-YEAR at end of standard number patterns
    m = re.search(r'(?:GB|GA|GY|YD|SJ|CJ|DBJ|JJF|CECS)[/\s]*(?:[T∕])?[\s]*\d+(?:\.\d+)?[-—](20\d{2}|19\d{2})', title)
    if m:
        return int(m.group(1))

    # Strategy 2: Standard number with year suffix — "TEGAG 021-2023", "GDZW 0082-2023"
    m = re.search(r'(?:TEGAG|GDZW|T/EGAG|GA/T|GB/T)[\s]*\d+(?:\.\d+)?[-—](20\d{2}|19\d{2})', title)
    if m:
        return int(m.group(1))

    # Strategy 3: Year in brackets/parentheses — "（2019年）", "(2018年版)", "（2026）"
    m = re.search(r'[（(](20\d{2}|19\d{2})[年)）]', title)
    if m:
        return int(m.group(1))

    # Strategy 4: Year in square brackets — "穗财资[2022]24号"
    m = re.search(r'\[(20\d{2}|19\d{2})\]\s*', title)
    if m:
        return int(m.group(1))

    # Strategy 5: Loose year at end — the title itself ends with a year
    m = re.search(r'[-—/](20\d{2}|19\d{2})\s*$', title)
    if m:
        return int(m.group(1))

    # Strategy 6: Four consecutive digits in title (loose)
    # Only use this for gb_standard where a year is almost certainly present
    # But be careful — some titles have other numbers
    # Try the first 4-digit sequence that looks like a year (20XX or 19XX)
    years = re.findall(r'(20\d{2}|19\d{2})', title)
    if years:
        # For gb_standard / regulation, take the first year
        if doc_type in ('gb_standard', 'regulation'):
            return int(years[0])
        # For generic, only take if it looks like a publication year (at end or after standard-like prefix)
        for y in years:
            if int(y) >= 2000:  # reasonable range
                return int(y)

    return None


# Preview first
print("\n=== EXTRACTION PREVIEW ===")
prev_type = None
for r in rows[:30]:
    doc_id, title, doc_type = r['doc_id'], str(r['title']), r['doc_type']
    
    if doc_type != prev_type:
        print(f"\n--- {doc_type} ---")
        prev_type = doc_type
    
    year = extract_year(title, doc_type)
    if year:
        print(f"  ✓ {doc_id[:12]}... → {year}-01-01 | {title[:60]}")
    else:
        print(f"  ✗ {doc_id[:12]}... → NO YEAR   | {title[:60]}")

print(f"\n{'='*60}")
if DRY_RUN:
    print("DRY RUN — no changes made")
else:
    # Execute
    updated_count = 0
    for r in rows:
        doc_id, title = r['doc_id'], str(r['title'])
        year = extract_year(title, r['doc_type'])
        if year:
            date_str = f"{year}-01-01"
            try:
                c.execute(
                    "UPDATE documents SET published_date = ? WHERE doc_id = ? AND (published_date IS NULL OR published_date = '')",
                    (date_str, doc_id)
                )
                if c.rowcount:
                    updated_count += 1
                    updates.append((doc_id, title, date_str))
            except Exception as e:
                errors.append((doc_id, str(e)))
        else:
            no_year.append((doc_id, title))

    conn.commit()
    print(f"\nUpdated {updated_count} documents with published_date")
    print(f"Docs with no year found: {len(no_year)}")
    print(f"Errors: {len(errors)}")

    if errors:
        print("\n=== ERRORS ===")
        for e in errors:
            print(f"  {e}")

    if no_year:
        print("\n=== NO YEAR FOUND (sample 20) ===")
        for doc_id, title in no_year[:20]:
            print(f"  {doc_id[:12]}... | {title[:60]}")

    # Verify
    c.execute("SELECT COUNT(*) FROM documents WHERE published_date IS NOT NULL AND published_date != ''")
    total = c.fetchone()[0]
    print(f"\n=== VERIFICATION ===")
    print(f"Total docs with published_date: {total}")
    
    c.execute("SELECT COUNT(*) FROM documents WHERE status='active' AND (published_date IS NULL OR published_date = '')")
    still_missing = c.fetchone()[0]
    print(f"Active docs still missing published_date: {still_missing}")

conn.close()
print("Done.")
