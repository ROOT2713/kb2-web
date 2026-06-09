#!/usr/bin/env python3
"""Hindsight tags回填脚本 — 修复空tags导致sources显示'未知文档'的问题

用法: python3 backfill_hindsight_tags.py [--dry-run]
"""
import json, sys, sqlite3, httpx, time

HINDSIGHT_URL = "http://localhost:8888"
DB_PATH = "/home/ubuntu/kb-web/data/kb.db"
DRY_RUN = "--dry-run" in sys.argv

def get_doc_titles():
    """从v2数据库获取doc_id→title映射"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT doc_id, title FROM documents").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def get_all_banks():
    resp = httpx.get(f"{HINDSIGHT_URL}/v1/default/banks", timeout=10)
    return [b["bank_id"] for b in resp.json().get("banks", []) if b.get("fact_count", 0) > 0]

def recall_all(bank, limit=500):
    """召回一个bank的所有记忆"""
    resp = httpx.post(f"{HINDSIGHT_URL}/v1/default/banks/{bank}/memories/recall",
        json={"query": "all documents", "limit": limit, "max_tokens": 999999}, timeout=30)
    return resp.json().get("results", [])

def main():
    titles = get_doc_titles()
    banks = get_all_banks()
    print(f"📊 {len(titles)} docs in kb.db, {len(banks)} active Hindsight banks")
    
    fixed = 0
    skipped = 0
    failed = 0
    
    for bank in banks:
        print(f"\n🔍 Scanning bank: {bank}")
        memories = recall_all(bank)
        print(f"   Found {len(memories)} memories")
        
        for mem in memories:
            mem_id = mem.get("id")
            tags = mem.get("tags", [])
            doc_id_from_tags = None
            title_from_tags = None
            
            for t in tags:
                if t.startswith("doc_id:"):
                    doc_id_from_tags = t[7:]
                if t.startswith("title:"):
                    title_from_tags = t[6:]
            
            # 跳过已有完整tags的记忆
            if doc_id_from_tags and title_from_tags:
                skipped += 1
                continue
            
            # 尝试从document_id回填
            doc_id = mem.get("document_id") or doc_id_from_tags
            if not doc_id:
                # 尝试从chunk_id解析
                cid = mem.get("chunk_id") or ""
                parts = cid.split("_")
                if len(parts) >= 3:
                    # format: bank_docid_idx
                    doc_id = parts[1] if len(parts[1]) > 10 else None
            
            if not doc_id or doc_id not in titles:
                failed += 1
                continue
            
            title = titles[doc_id]
            
            # 构建新tags
            new_tags = list(tags)
            if not doc_id_from_tags:
                new_tags.append(f"doc_id:{doc_id}")
            if not title_from_tags:
                new_tags.append(f"title:{title}")
            
            if DRY_RUN:
                print(f"   [DRY] {mem_id[:8]}... → title={title[:30]}, doc_id={doc_id[:8]}")
                fixed += 1
            else:
                # Hindsight PATCH更新tags
                try:
                    # 先删除旧记忆再创建（Hindsight不支持直接PATCH tags）
                    # 用recall的text重建
                    text = mem.get("text", "")
                    if not text:
                        failed += 1
                        continue
                    
                    resp = httpx.post(
                        f"{HINDSIGHT_URL}/v1/default/banks/{bank}/memories",
                        json={"items": [{"content": text, "tags": new_tags, "type": "world"}]},
                        timeout=30
                    )
                    if resp.status_code == 200:
                        fixed += 1
                        if fixed % 50 == 0:
                            print(f"   ✅ Fixed {fixed} so far...")
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    
            time.sleep(0.05)  # 限速
    
    print(f"\n{'='*50}")
    print(f"📊 结果: fixed={fixed}, skipped(已有tags)={skipped}, failed={failed}")
    if DRY_RUN:
        print("⚠️  DRY RUN — 没有实际修改。去掉 --dry-run 参数执行实际回填。")

if __name__ == "__main__":
    main()
