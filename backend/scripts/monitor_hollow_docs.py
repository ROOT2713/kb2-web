"""
Hollow Doc Monitor — scans kb2-web SQLite for document health issues.
Run periodically (or via cron) to detect document anomalies.

Detection targets:
  1. searchable=1, parent_chunks=0  (hollow — can never be retrieved)
  2. searchable=0, parent_chunks>0  (fixable — has content but invisible)
  3. active + searchable=1 + no pgvector embedding (missing semantic index)
"""
import sqlite3, subprocess, time

KB_DB = "/home/ubuntu/kb-web/data/kb.db"
PG_DSN = "postgresql://hindsight:hindsight123@localhost:5432/hindsight"

def red(s): return f"\033[91m{s}\033[0m"
def yel(s): return f"\033[93m{s}\033[0m"
def grn(s): return f"\033[92m{s}\033[0m"

def report():
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== kb2-web Document Health Monitor @ {ts} ===\n")
    
    conn = sqlite3.connect(KB_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Total
    cur.execute("SELECT COUNT(*) FROM documents WHERE status='active'")
    total_docs = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM documents WHERE status='active' AND searchable=1")
    searchable_docs = cur.fetchone()[0]
    
    # 1. Hollow: searchable=1 but no content
    cur.execute("""
        SELECT d.doc_id, d.title, d.bank, d.category
        FROM documents d
        WHERE d.status='active' AND d.searchable=1
          AND NOT EXISTS (SELECT 1 FROM parent_chunks pc WHERE pc.doc_id = d.doc_id AND length(pc.parent_text) > 20)
    """)
    hollow = cur.fetchall()
    print(f"1. {red('Hollow docs')} (searchable=1, no content): {len(hollow)}")
    for r in hollow:
        print(f"   [{r['bank']}] {str(r['title'])[:60]}")
    
    # 2. Fixable: searchable=0 but has content
    cur.execute("""
        SELECT d.doc_id, d.title, d.bank, d.hs_bank,
               (SELECT COUNT(*) FROM parent_chunks pc WHERE pc.doc_id = d.doc_id AND length(pc.parent_text) > 20) as pc_count
        FROM documents d
        WHERE d.status='active' AND d.searchable=0
          AND EXISTS (SELECT 1 FROM parent_chunks pc WHERE pc.doc_id = d.doc_id AND length(pc.parent_text) > 20)
        ORDER BY d.doc_id
    """)
    fixable = cur.fetchall()
    print(f"\n2. {yel('Fixable docs')} (searchable=0, has content): {len(fixable)}")
    for r in fixable:
        print(f"   [{r['bank']}] {str(r['title'])[:60]}  ({r['pc_count']} chunks)")
    
    # 3. Check pgvector coverage
    r = subprocess.run(["psql", PG_DSN, "-tA", "-c", "SELECT COUNT(DISTINCT doc_id) FROM vector_chunks"],
                     capture_output=True, text=True, timeout=10, env={"PGPASSWORD":"hindsight123"})
    pgv_doc_ids = int(r.stdout.strip())
    
    # Count SQLite searchable=1 docs NOT in pgvector
    cur.execute("""
        SELECT COUNT(*) FROM documents d
        WHERE d.status='active' AND d.searchable=1
          AND EXISTS (SELECT 1 FROM parent_chunks pc WHERE pc.doc_id = d.doc_id AND length(pc.parent_text) > 20)
    """)
    sq_content_docs = cur.fetchone()[0]
    
    print(f"\n3. {yel('pgvector coverage')}:")
    print(f"   SQLite docs with content: {sq_content_docs}")
    print(f"   pgvector distinct doc_ids: {pgv_doc_ids}")
    diff = max(0, sq_content_docs - pgv_doc_ids)
    print(f"   Gap: {red(str(diff)) if diff > 0 else grn('0')}")
    
    # 4. Summary
    total_bad = len(hollow) + len(fixable) + diff
    status = red("⚠️ ISSUES") if total_bad > 0 else grn("✅ OK")
    print(f"\n--- {status} ---")
    print(f"Total docs: {total_docs} (searchable: {searchable_docs})")
    print(f"Issues: hollow={len(hollow)}, fixable={len(fixable)}, pgvector gap={diff}")
    
    conn.close()

if __name__ == "__main__":
    report()
