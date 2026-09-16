#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 批量正主恢复：从 7/15 备份导出正文 → 上传 → 归并碎片。

出处: kb2 数据治理 0904 会话 P1
前提: 试点（GB/T 28448-2019）已验证通过

用法:
  python3 p1_batch_recover.py --titles "22239,50348,验收管理细则"      # dry-run
  python3 p1_batch_recover.py --titles "22239,50348,验收管理细则" --apply
  python3 p1_batch_recover.py --list                                   # 列出可恢复组

凭据: 从 backend/.env 读，不打印。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:3027"
BACKEND = "/home/ubuntu/kb2-web/backend"
ENV_PATH = os.path.join(BACKEND, ".env")
OLD_DB = "/data/projects/kb-web/data/kb.db.bak.20260715_120804"
NOW_DB = "/home/ubuntu/kb-web/data/kb.db"
OUTDIR = "/tmp/p1_recover"
SOURCE = "p1_recover"


def load_env():
    cfg = {}
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def login():
    cfg = load_env()
    body = json.dumps({"username": cfg.get("ADMIN_USERNAME"),
                       "password": cfg.get("ADMIN_PASSWORD")}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def export_from_backup(title_like, slug):
    """从 7/15 备份导出该标题对应 doc 的完整正文。"""
    con = sqlite3.connect(f"file:{OLD_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    row = cur.execute(
        "SELECT d.doc_id, d.title, d.bank, d.hs_bank FROM documents d "
        "WHERE d.title LIKE ? AND EXISTS (SELECT 1 FROM parent_chunks p "
        "  WHERE p.doc_id=d.doc_id) "
        "ORDER BY (SELECT COALESCE(SUM(length(parent_text)),0) FROM parent_chunks p2 "
        "  WHERE p2.doc_id=d.doc_id) DESC LIMIT 1", (f"%{title_like}%",)).fetchone()
    if not row:
        con.close()
        return None
    did, title = row["doc_id"], row["title"]
    bank = row["bank"] or "general"
    hs_bank = row["hs_bank"] or ""
    parts = [r["parent_text"] or "" for r in cur.execute(
        "SELECT parent_text FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
        (did,)).fetchall()]
    con.close()
    text = "\n\n".join(parts)
    os.makedirs(OUTDIR, exist_ok=True)
    import hashlib
    h = hashlib.md5(did.encode()).hexdigest()[:6]
    path = os.path.join(OUTDIR, f"{slug}_{h}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"doc_id": did, "title": title, "chars": len(text), "path": path,
            "bank": bank, "hs_bank": hs_bank}


def upload(token, path, title, bank="standards"):
    with open(path, "rb") as f:
        payload = f.read()
    fname = os.path.basename(path)
    boundary = "----p1" + uuid.uuid4().hex
    parts = []
    for k, v in (("title", title), ("bank", bank), ("source", SOURCE),
                 ("category", "standard"), ("subcategory", "")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f"filename=\"{fname}\"\r\nContent-Type: text/plain\r\n\r\n")
    data = "".join(parts).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/upload", data=data,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def poll(token, task_id, max_s=2400):
    t0 = time.time()
    last = None
    while time.time() - t0 < max_s:
        time.sleep(5)
        rq = urllib.request.Request(BASE + f"/api/upload/tasks/{task_id}",
                                    headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(rq, timeout=30) as rr:
                st = json.loads(rr.read().decode())
        except Exception:
            continue
        cur = f"{st.get('status')}|{st.get('stage')}|{st.get('progress')}"
        if cur != last:
            print(f"      [{int(time.time()-t0)}s] {cur}", flush=True)
            last = cur
        if st.get("status") in ("done", "completed", "success", "failed", "error"):
            return st
    return {"status": "timeout"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles", default="", help="逗号分隔的标题关键词")
    ap.add_argument("--bank", default="standards")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", action="store_true", help="列出可恢复组")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"

    if args.list:
        con = sqlite3.connect(f"file:{OLD_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT d.title, COUNT(p.parent_idx) n, SUM(length(p.parent_text)) c "
            "FROM documents d JOIN parent_chunks p ON p.doc_id=d.doc_id "
            "GROUP BY d.doc_id ORDER BY c DESC").fetchall()
        print(f"7/15 备份可恢复 doc: {len(rows)}")
        for r in rows:
            print(f"   {r['c']:>7d} 字符 / {r['n']:>4d} 块  {str(r['title'])[:70]}")
        con.close()
        return 0

    keys = [k.strip() for k in args.titles.split(",") if k.strip()]
    if not keys:
        print("指定 --titles 或 --list")
        return 1

    print(f"== P1 批量恢复 [{mode}] ==")
    targets = []
    for k in keys:
        info = export_from_backup(k, re.sub(r"[^A-Za-z0-9_.-]", "_", k)[:40])
        if info:
            targets.append((k, info))
            print(f"  {k}: 导出 {info['chars']} 字符 → {info['path']}")
            print(f"      备份源 title = {info['title']}  (bank={info['bank']} / hs={info['hs_bank']})")
        else:
            print(f"  {k}: [跳过] 备份中无可恢复正文")

    if not args.apply:
        print("\n[DRY-RUN] 未上传。加 --apply 执行。")
        return 0

    token = login()
    print(f"\n上传 {len(targets)} 个文档...")
    results = []
    for k, info in targets:
        print(f"\n  >>> {info['title'][:60]}")
        resp = upload(token, info["path"], info["title"], info["bank"] or args.bank)
        st = poll(token, resp["task_id"])
        res = {"key": k, "title": info["title"], "status": st.get("status"),
               "doc_id": st.get("result_doc_id"), "stage": st.get("stage")}
        results.append(res)
        print(f"      结果: {res}")

    print("\n== 汇总 ==")
    for r in results:
        print(f"  {r['status']:10s} {str(r['doc_id'])[:8]:8s} {r['title'][:56]}")

    # 归并碎片
    ok_keys = [r["key"] for r in results if r["status"] in ("done", "completed", "success")]
    if ok_keys:
        print(f"\n归并碎片（{len(ok_keys)} 组）...")
        import subprocess
        for k in ok_keys:
            cp = subprocess.run(
                [sys.executable, os.path.join(BACKEND, "scripts/p1_merge_fragments.py"),
                 "--apply", "--title-filter", k],
                capture_output=True, text=True, timeout=600)
            tail = [ln for ln in cp.stdout.strip().splitlines() if ln.strip()][-3:]
            print(f"  [{k}] " + " | ".join(tail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
