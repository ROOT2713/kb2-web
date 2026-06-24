#!/usr/bin/env python3
"""批量重索引存量文档到 Hindsight（仅缺失的补索引）

两步策略：
  1. doc_id 级去重：检查 Hindsight /documents 中是否有 doc_id tag
  2. 仅 POST 那些完全缺失的文档的全部 chunks
"""

import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HS_URL = "http://localhost:8888"
DB_PATH = "/home/ubuntu/kb-web/data/kb.db"

BANK_TO_HS = {
    "project_docs": "kb_project", "standards": "kb_standard",
    "industry_docs": "kb_industry", "tech_guides": "kb_tech",
    "general": "kb_general", "checklist": "kb_checklist",
    "xhs": "kb_xhs", "business": "kb_general", "methodology": "kb_general",
}

# Which Hindsight banks need reindexing (bank_id -> name)
REINDEX_BANKS = {
    "kb_general": "general",
    "kb_standard": "standards",
    "kb_industry": "industry_docs",
    "kb_project": "project_docs",
    "kb_checklist": "checklist",
    "kb_tech": "tech_guides",
    "kb_xhs": "xhs",
}


def _recall_check(hs_bank: str, query: str, limit: int = 5) -> list:
    """通过 recall 验证文档是否存在"""
    payload = json.dumps({"query": query, "limit": limit}).encode()
    req = urllib.request.Request(
        f"{HS_URL}/v1/default/banks/{hs_bank}/memories/recall",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read()).get("results", [])
    except Exception as e:
        return []


def _post_memories(hs_bank: str, items: list) -> dict:
    payload = json.dumps({"items": items}).encode()
    req = urllib.request.Request(
        f"{HS_URL}/v1/default/banks/{hs_bank}/memories",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=300)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200] if e.fp else ""
        raise Exception(f"HTTP {e.code}: {detail}")
    except Exception as e:
        raise Exception(str(e))


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 收集所有待处理文档，按 Hindsight bank 分组
    cur.execute("SELECT doc_id, title, bank, source, category FROM documents")
    all_docs = cur.fetchall()
    log.info("SQLite 文档总数: %d", len(all_docs))

    # 按 bank 分组
    docs_by_hs = {}
    for doc in all_docs:
        hs_bank = BANK_TO_HS.get(doc["bank"])
        if not hs_bank:
            continue
        docs_by_hs.setdefault(hs_bank, []).append(doc)

    log.info("各 bank 待处理文档数:")
    for hs_bank in REINDEX_BANKS:
        cnt = len(docs_by_hs.get(hs_bank, []))
        log.info("  %s: %d docs", hs_bank, cnt)

    # 逐 bank 处理
    batch_size = 20
    total_new = 0
    total_skip = 0
    total_err = 0
    start = time.time()

    for hs_bank, sqlite_bank_name in sorted(REINDEX_BANKS.items()):
        docs = docs_by_hs.get(hs_bank, [])
        if not docs:
            continue

        log.info("===== 处理 %s (%s): %d docs =====", hs_bank, sqlite_bank_name, len(docs))

        for doc in docs:
            doc_id = doc["doc_id"]
            title = doc["title"]
            category = doc["category"] or ""

            # 获取 chunks
            cur.execute(
                "SELECT parent_idx, parent_text FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
                (doc_id,)
            )
            chunks = [r["parent_text"] for r in cur.fetchall()]
            if not chunks:
                log.warning("  [SKIP] %s: no chunks", title[:40])
                total_skip += 1
                continue

            # 快速检测：用 recall 看文档是否已存在
            # 取第一个 chunk 的前 80 字搜索
            recall_term = title[:40]
            existing = _recall_check(hs_bank, recall_term, limit=3)
            already_indexed = False
            for r in existing:
                tags = r.get("tags", [])
                for t in tags:
                    if f"doc_id:{doc_id}" in t or f"title:{title[:30]}" in t:
                        already_indexed = True
                        break
                if already_indexed:
                    break

            if already_indexed:
                log.info("  [SKIP] %s: already in %s", title[:40].ljust(40), hs_bank)
                total_skip += 1
                continue

            # 构建 memory items 并 POST
            memory_items = []
            for idx, chunk_text in enumerate(chunks):
                if not chunk_text or not chunk_text.strip():
                    continue
                tags = [
                    f"doc_id:{doc_id}",
                    f"title:{title}",
                    f"chunk:{idx + 1}/{len(chunks)}",
                ]
                if category:
                    tags.append(f"cat:{category}")
                memory_items.append({
                    "content": chunk_text,
                    "tags": tags,
                    "type": "world",
                })

            if not memory_items:
                log.warning("  [SKIP] %s: all empty chunks", title[:40])
                continue

            # 分批 POST
            success = 0
            failed = False
            for batch_start in range(0, len(memory_items), batch_size):
                batch = memory_items[batch_start:batch_start + batch_size]
                try:
                    result = _post_memories(hs_bank, batch)
                    success += result.get("items_count", len(batch))
                except Exception as e:
                    log.error("  [ERR] %s batch %d: %s", title[:40],
                              batch_start // batch_size + 1, str(e)[:80])
                    failed = True
                    total_err += 1
                    break

            total_new += success
            status = "FAIL" if failed else "OK"
            log.info("  [%s] %s -> %s: %d chunks (+%d new)",
                     status, title[:40].ljust(40), hs_bank, len(chunks), success)

    elapsed = time.time() - start
    log.info("=" * 60)
    log.info("完成！")
    log.info("  新增索引: %d chunks", total_new)
    log.info("  跳过: %d docs", total_skip)
    log.info("  错误: %d docs", total_err)
    log.info("  耗时: %.1fs (%.1f 分钟)", elapsed, elapsed / 60)

    conn.close()
    return total_new > 0


if __name__ == "__main__":
    main()
