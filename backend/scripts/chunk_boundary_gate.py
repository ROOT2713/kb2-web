"""Chunk Boundary Integrity Gate
检测 parent_chunks 中的断裂问题并报告/修复。

检测维度:
1. HTML表格跨chunk（<table> 无 </table> close）
2. 章节标题在chunk末尾被截断（##... 后无闭合）
3. 管道符markdown表格跨chunk（|---| 在上一chunk末尾打开）

用法:
  python3 chunk_boundary_gate.py check [doc_id]     # 检测
  python3 chunk_boundary_gate.py audit               # 全库扫描
  python3 chunk_boundary_gate.py repair [doc_id]     # 修复
"""
import sqlite3, re, sys

DB_PATH = "/home/ubuntu/kb-web/data/kb.db"

def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def scan_doc(db, doc_id):
    """Scan a single document for chunk boundary issues."""
    issues = []
    cur = db.execute(
        "SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
        (doc_id,)
    )
    chunks = cur.fetchall()
    
    for i, chunk in enumerate(chunks):
        idx, text = chunk["parent_idx"], chunk["parent_text"]
        next_text = chunks[i+1]["parent_text"] if i+1 < len(chunks) else ""
        
        clues = []
        
        # Pattern 1: HTML table opened but not closed in this chunk
        table_open = text.count("<table")
        table_close = text.count("</table>")
        if table_open > table_close:
            # Need to check if the open is at the end (likely broken)
            last_table_pos = text.rfind("<table")
            rest_after_table = text[last_table_pos+7:]
            if "</table>" not in rest_after_table:
                clues.append(f"html_table_split")
        
        # Pattern 2: Table row started but not finished (end of chunk)
        tr_open = text.rfind("<tr")
        tr_close_last = text.rfind("</tr>")
        if tr_open > tr_close_last:
            clues.append("html_tr_split")
        
        # Pattern 3: Chunk ends with partial HTML tag
        ends_with_td_open = bool(re.search(r'<td[^>]*>$', text))
        if ends_with_td_open:
            clues.append("html_td_unclosed")
        
        # Pattern 4: Markdown table started but not ended
        md_table_header = bool(re.search(r'^\|.*\|$', text, re.MULTILINE))
        md_table_break = bool(re.search(r'^\|?\s*:?-+:?\s*\|', text, re.MULTILINE))
        if md_table_header or md_table_break:
            # Check if this is the start of a table that continues
            last_line = text.strip().split('\n')[-1].strip()
            if last_line.startswith('|') and not last_line.endswith('|'):
                clues.append("md_table_split")
        
        # Pattern 5: 表格标题存在但表格不完整
        has_table_title = bool(re.search(r'【表格标题】表\d+', text))
        if has_table_title and table_open == 0:
            # Title mentions a table but no HTML table in this chunk
            # Check if table is in next chunk
            if not re.search(r'<table|<tr>|^\|', next_text[:200]):
                clues.append("table_title_no_content")
        
        # Pattern 6: Section heading at end (likely split across boundary)
        heading_at_end = bool(re.search(r'(?:##\s+\S|【.*】)\s*$', text[:100]))
        if heading_at_end and next_text and not re.search(r'^\s*##', next_text[:100]):
            clues.append("heading_split")
        
        if clues:
            issues.append({
                "parent_idx": idx,
                "clues": clues,
                "chunk_size": len(text),
                "first_200": text[:200],
                "last_200": text[-200:],
            })
    
    return issues

def audit_all(db):
    """Scan all documents for issues."""
    cur = db.execute("SELECT doc_id, title FROM documents ORDER BY doc_id")
    total_docs = 0
    total_issues = 0
    docs_with_issues = []
    
    for row in cur:
        total_docs += 1
        issues = scan_doc(db, row["doc_id"])
        if issues:
            docs_with_issues.append((row["doc_id"], row["title"], issues))
            total_issues += len(issues)
    
    return total_docs, total_issues, docs_with_issues

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "audit"
    doc_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    db = connect()
    
    if action == "check" and doc_id:
        issues = scan_doc(db, doc_id)
        print(f"=== {doc_id[:30]} ===")
        if issues:
            print(f"Found {len(issues)} issues:")
            for iss in issues:
                print(f"  [{iss['parent_idx']}] {iss['clues']} ({iss['chunk_size']} chars)")
                print(f"     start: {iss['first_200'][:80]}")
                print(f"     end:   {iss['last_200'][:80]}")
        else:
            print("No issues found")
    
    elif action == "audit":
        total, issues, docs = audit_all(db)
        print(f"=== Chunk Boundary Audit ===")
        print(f"Total documents: {total}")
        print(f"Documents with issues: {len(docs)}")
        print(f"Total boundary issues: {issues}")
        for doc_id, title, iss in docs[:10]:
            print(f"\n  {title[:50]} ({len(iss)} issues):")
            for i in iss:
                print(f"    [{i['parent_idx']}] {'|'.join(i['clues'])} ({i['chunk_size']} chars)")
        if len(docs) > 10:
            print(f"  ... and {len(docs)-10} more")
    
    elif action == "repair" and doc_id:
        issues = scan_doc(db, doc_id)
        if not issues:
            print(f"No issues to repair for {doc_id[:30]}")
            db.close()
            sys.exit(0)
        print(f"Repairing {len(issues)} issues for doc {doc_id[:30]}...")
        fixed = 0
        cur = db.execute(
            "SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
            (doc_id,)
        )
        all_chunks = {r["parent_idx"]: r["parent_text"] for r in cur.fetchall()}
        indices = sorted(all_chunks.keys())
        delete_indices = set()
        merge_ops = {}
        for iss in issues:
            if "table_title_no_content" in iss["clues"]:
                pi = iss["parent_idx"]
                next_idx = None
                for idx in indices:
                    if idx > pi:
                        next_idx = idx
                        break
                if next_idx is not None:
                    merge_ops.setdefault(next_idx, [])
                    merge_ops[next_idx].append((pi, all_chunks[pi]))
                    delete_indices.add(pi)
                    fixed += 1
        for target_idx, ops in merge_ops.items():
            for src_idx, src_text in sorted(ops, reverse=True):
                new_text = src_text + "\n" + all_chunks[target_idx]
                db.execute(
                    "UPDATE parent_chunks SET parent_text=? WHERE doc_id=? AND parent_idx=?",
                    (new_text, doc_id, target_idx)
                )
        for di in sorted(delete_indices, reverse=True):
            db.execute(
                "DELETE FROM parent_chunks WHERE doc_id=? AND parent_idx=?",
                (doc_id, di)
            )
        db.commit()
        print(f"Fixed {fixed} table_title_no_content issues")
        print(f"Deleted {len(delete_indices)} orphan title-only chunks")
        print(f"NOTE: pgvector chunks remain unchanged — need re-index for full sync")
    
    db.close()
