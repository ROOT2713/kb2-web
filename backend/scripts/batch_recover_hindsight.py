#!/usr/bin/env python3
"""
批量恢复脚本 — 修复 Hindsight 索引不完整的文档。

用法：
  python3 scripts/batch_recover_hindsight.py            # 修复所有 searchable=0
  python3 scripts/batch_recover_hindsight.py --dry-run  # 只检查不写入

Hindsight API 格式：
  POST /v1/default/banks/{bank}/memories
  {"items": [{"content": str, "tags": [...], "type": "world"}]}

  POST /v1/default/banks/{bank}/memories/recall
  {"query": str, "limit": int}  ← 不支持标签过滤
"""
import requests, sqlite3, time, sys

DB = "/home/ubuntu/kb-web/data/kb.db"
HS = "http://localhost:8888"
BANK_MAP = {
    "standards": "kb_standard", "industry_docs": "kb_industry",
    "general": "kb_general", "business": "kb_general",
    "project_docs": "kb_project", "methodology": "kb_general",
    "tech_guides": "kb_standard", "checklist": "kb_checklist",
}

DRY_RUN = "--dry-run" in sys.argv

def push_doc_chunks(doc_id, title, hs_bank, rows):
    """按批写入 chunks 到 Hindsight，大文档自动缩减批次"""
    n = len(rows)
    B = 5 if n > 100 else 10 if n > 20 else 20
    TO = max(60, min(B * 6, 300))
    total_ok = 0

    for start in range(0, n, B):
        batch = rows[start:start+B]
        items = []
        for row in batch:
            content = f"[文档:{title}] {row['parent_text']}"
            items.append({
                "content": content,
                "tags": [f"doc_id:{doc_id}", f"title:{title[:60]}", f"idx:{row['parent_idx']}"],
                "type": "world",
            })
        t0 = time.time()
        try:
            r = requests.post(
                f"{HS}/v1/default/banks/{hs_bank}/memories",
                json={"items": items},
                timeout=TO
            )
            el = time.time() - t0
            if r.status_code in (200, 201):
                cnt = r.json().get("items_count", len(items))
                total_ok += cnt
                print(f"    batch[{start//B+1}/{n//B+1}] {cnt}/{len(items)} ✅ {el:.0f}s")
            else:
                print(f"    batch[{start//B+1}/{n//B+1}] HTTP {r.status_code} {el:.0f}s: {r.text[:80]}")
        except Exception as e:
            print(f"    batch[{start//B+1}/{n//B+1}] ❌ {e}")
            if "read timeout" in str(e).lower() or "write timeout" in str(e).lower():
                print("      超时，单条重试...")
                # 逐条写入
                for item in items:
                    try:
                        r2 = requests.post(
                            f"{HS}/v1/default/banks/{hs_bank}/memories",
                            json={"items": [item]},
                            timeout=TO
                        )
                        if r2.status_code in (200, 201):
                            total_ok += 1
                    except:
                        print(f"      单条也超时，跳过")
            continue

    return total_ok


def main():
    print("=" * 60)
    print(f"批量 Hindsight 索引恢复")
    print(f"DB: {DB}")
    print(f"HS: {HS}")
    if DRY_RUN:
        print("  🔍 DRY RUN — 仅检查，不写入")
    print("=" * 60)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 找出 searchable=0 的文档
    c.execute("""
        SELECT d.doc_id, d.title, d.bank,
               (SELECT COUNT(*) FROM parent_chunks WHERE doc_id = d.doc_id) as n
        FROM documents d
        WHERE status = 'active'
          AND searchable = 0
        ORDER BY n ASC
    """)
    docs = c.fetchall()

    print(f"\n需要修复: {len(docs)} 个")

    for d in docs:
        doc_id, title, bank = d["doc_id"], d["title"], d["bank"]
        n = d["n"]
        hs_bank = BANK_MAP.get(bank, "kb_general")
        print(f"\n[{doc_id[:12]}] {title[:48]} ({n} chunks, {hs_bank})")

        c2 = conn.cursor()
        c2.execute(
            "SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
            (doc_id,)
        )
        rows = c2.fetchall()

        if DRY_RUN:
            print(f"  → 需写入 {len(rows)} chunks")
            continue

        ok = push_doc_chunks(doc_id, title, hs_bank, rows)

        if ok > 0:
            c2.execute("UPDATE documents SET searchable=1 WHERE doc_id=?", (doc_id,))
            conn.commit()
            print(f"  ✅ {ok}/{n} → searchable=1")
        else:
            print(f"  ❌ 写入 0/{n}")

    # 最终检查
    c.execute("SELECT COUNT(*) FROM documents WHERE searchable=0 AND status='active'")
    remaining = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM documents")
    total = c.fetchone()[0]
    print(f"\n{'=' * 60}")
    print(f"最终状态：总 {total} 文档, searchable=0: {remaining}")
    if remaining == 0:
        print("✅ 全部可检索")
    elif remaining == len(docs):
        print(f"❌ {remaining} 个未修复")
    else:
        print(f"⚠️ 还有 {remaining} 个未修复")
    conn.close()

if __name__ == "__main__":
    main()
