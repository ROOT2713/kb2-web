#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 治本 — 计划执行器（一次性运维脚本）

出处: kb2 数据治理 0904 会话 P1 阶段
读 /tmp/p1_plan.tsv，按分类执行:
  A_原件重传  上传磁盘原件 → 归并碎片
  B_备份恢复  从 7/15 备份导出正文 → 上传 → 归并碎片
  C_仅清碎片  已有更好 manual 版本 → 只撤销碎片
  D_剔除      撤销碎片（内容定性剔除，保留记录可回滚）
  E_垃圾删除  撤销碎片（测试垃圾）

用法:
  python3 p1_execute_plan.py                        # dry-run
  python3 p1_execute_plan.py --apply                # 全量执行
  python3 p1_execute_plan.py --apply --only A       # 只跑 A 类
  python3 p1_execute_plan.py --apply --title-contains 394-2002
  python3 p1_execute_plan.py --apply --skip-upload  # 只做归并/撤销

凭据: 从 backend/.env 读，不打印。
回滚: /home/ubuntu/kb-web/data/kb.db.p1bak.202609160025
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
from collections import defaultdict
from datetime import datetime, timezone

BASE = "http://127.0.0.1:3027"
BACKEND = "/home/ubuntu/kb2-web/backend"
ENV_PATH = os.path.join(BACKEND, ".env")
PLAN = "/tmp/p1_plan.tsv"
NOW_DB = "/home/ubuntu/kb-web/data/kb.db"
OLD_DB = "/data/projects/kb-web/data/kb.db.bak.20260715_120804"
OUTDIR = "/tmp/p1_recover2"
SOURCE = "p1_recover"
FRAG_SOURCE = "backfill_0904"

# 覆盖 /tmp/p1_plan.tsv 的分类：造价指导书系列 → 剔除（本轮不做，超大件）
OVERRIDE_EXCLUDE = ["造价指导书（2019年）"]
BACKUP_LIMIT_CHARS = 400000

CT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


def load_env():
    cfg = {}
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def dsn_from(cfg):
    for k in ("pgvector_database_url", "PGVECTOR_DATABASE_URL", "DATABASE_URL"):
        if cfg.get(k):
            return cfg[k]
    return ""


def login(cfg):
    body = json.dumps({"username": cfg.get("ADMIN_USERNAME"),
                       "password": cfg.get("ADMIN_PASSWORD")}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def clean_name(path):
    """剥离 v1 前缀，得到干净文件名。"""
    base = os.path.basename(path)
    m = re.search(r"doc_[0-9a-f]{8,}_(.+)$", base)
    if m:
        return m.group(1)
    return re.sub(r"^[0-9a-f]{8}_", "", base)


def upload(token, payload, fname, title, bank, source=SOURCE):
    ext = os.path.splitext(fname)[1].lower()
    ctype = CT.get(ext, "application/octet-stream")
    boundary = "----p1x" + uuid.uuid4().hex
    fields = (("title", title), ("bank", bank), ("source", source),
              ("category", "standard"), ("subcategory", ""))
    chunks = []
    for k, v in fields:
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                      f'name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
    enc = urllib.parse.quote(fname)
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{fname}\"; filename*=UTF-8''{enc}\r\n"
        f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
    chunks.append(payload)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    data = b"".join(chunks)
    req = urllib.request.Request(
        BASE + "/api/upload", data=data,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
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


# ---------------- SQLite / pg ----------------

def q_banks(cur, titles):
    """返回 {title: (bank, hs_bank, n_frag)}"""
    out = {}
    for t in titles:
        rows = cur.execute(
            "SELECT bank, hs_bank, COUNT(*) FROM documents WHERE title=? AND source=? "
            "AND status='active' GROUP BY bank, hs_bank", (t, FRAG_SOURCE)).fetchall()
        if rows:
            rows.sort(key=lambda r: -r[2])
            out[t] = rows[0]
    return out


def frag_ids(cur, title):
    return [r[0] for r in cur.execute(
        "SELECT doc_id FROM documents WHERE title=? AND source=? AND status='active'",
        (title, FRAG_SOURCE)).fetchall()]


def find_new_doc(cur, title):
    r = cur.execute("SELECT doc_id FROM documents WHERE title=? AND source=? "
                    "AND status='active' ORDER BY created_at DESC LIMIT 1",
                    (title, SOURCE)).fetchone()
    return r[0] if r else None


def find_better_doc(cur, title):
    r = cur.execute("SELECT doc_id FROM documents WHERE title=? AND source IN ('manual') "
                    "AND status='active' ORDER BY created_at DESC LIMIT 1", (title,)).fetchone()
    return r[0] if r else None


def supersede(dsn, ids, new_doc_id, reason):
    pg_rowcount = 0
    if dsn:
        try:
            import psycopg2
            pg = psycopg2.connect(dsn)
            pc = pg.cursor()
            pc.execute("DELETE FROM vector_chunks WHERE doc_id = ANY(%s)", (ids,))
            pg_rowcount = pc.rowcount
            pg.commit()
            pg.close()
        except Exception as e:  # noqa: BLE001
            print(f"      [WARN] pg 删除失败: {e}")
    return pg_rowcount


def export_from_backup(title_like):
    con = sqlite3.connect(f"file:{OLD_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    row = cur.execute(
        "SELECT d.doc_id, d.title, d.bank FROM documents d "
        "WHERE d.title LIKE ? AND EXISTS (SELECT 1 FROM parent_chunks p "
        "  WHERE p.doc_id=d.doc_id) "
        "ORDER BY (SELECT COALESCE(SUM(length(parent_text)),0) FROM parent_chunks p2 "
        "  WHERE p2.doc_id=d.doc_id) DESC LIMIT 1", (f"%{title_like}%",)).fetchone()
    if not row:
        con.close()
        return None
    did, title, bank = row["doc_id"], row["title"], row["bank"] or "general"
    parts = [r["parent_text"] or "" for r in cur.execute(
        "SELECT parent_text FROM parent_chunks WHERE doc_id=? ORDER BY parent_idx",
        (did,)).fetchall()]
    con.close()
    text = "\n\n".join(parts)
    if len(text) > BACKUP_LIMIT_CHARS:
        print(f"      [跳过] 备份正文 {len(text)} 字符超限")
        return None
    os.makedirs(OUTDIR, exist_ok=True)
    h = re.sub(r"[^A-Za-z0-9]", "_", title)[:36]
    path = os.path.join(OUTDIR, f"{h}_{did[:6]}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"title": title, "chars": len(text), "path": path, "bank": bank}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔类别字母 A,B,C,D,E")
    ap.add_argument("--title-contains", default="", help="只处理标题含该串的组")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-upload", action="store_true", help="只做归并/撤销")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"

    cfg = load_env()
    dsn = dsn_from(cfg)
    only = {c.strip().upper() for c in args.only.split(",") if c.strip()}

    # ---- 读计划 ----
    rows = []
    with open(PLAN, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 5:
                continue
            cls, nfrag, sz, extra, title = p[0], int(p[1]), p[2], p[3], p[4]
            letter = cls.split("_")[0]
            if any(k in title for k in OVERRIDE_EXCLUDE):
                letter, cls = "D", "D_剔除"
            if only and letter not in only:
                continue
            if args.title_contains and args.title_contains not in title:
                continue
            rows.append({"cls": cls, "letter": letter, "nfrag": nfrag,
                         "sz": sz, "extra": extra, "title": title})

    if args.limit:
        rows = rows[:args.limit]

    con = sqlite3.connect(NOW_DB)
    cur = con.cursor()
    banks = q_banks(cur, [r["title"] for r in rows])

    # ---- A 类按原件分组 ----
    groups = defaultdict(lambda: {"titles": [], "paths": set(), "frags": 0})
    for r in rows:
        if r["letter"] == "A":
            key = r["extra"] or r["title"]
            groups[key]["titles"].append(r["title"])
            groups[key]["paths"].add(r["extra"])
            groups[key]["frags"] += r["nfrag"]

    print(f"== P1 计划执行 [{mode}] ==")
    print(f"SQLite: {NOW_DB}")
    print(f"pg:     {'OK' if dsn else '<MISSING>'}")
    print(f"行数: {len(rows)}   A组(按原件): {len(groups)}\n")

    print("-- A 原件重传 --")
    for k, g in sorted(groups.items(), key=lambda x: -x[1]["frags"]):
        print(f"   {g['frags']:>3} 碎片  {len(g['titles'])} 标题  {os.path.basename(k)[:70]}")
    for L, name in (("B", "备份恢复"), ("C", "仅清碎片"), ("D", "剔除"), ("E", "垃圾")):
        sub = [r for r in rows if r["letter"] == L]
        if sub:
            print(f"\n-- {L} {name} ({len(sub)} 组 / {sum(r['nfrag'] for r in sub)} 碎片) --")
            for r in sub:
                print(f"   {r['nfrag']:>3} 碎片  {r['extra'][:30]:<30} {r['title'][:54]}")

    if not args.apply:
        print("\n[DRY-RUN] 未写入。加 --apply 执行。")
        return 0

    token = login(cfg)
    now = datetime.now(timezone.utc).isoformat()
    stats = defaultdict(int)
    failures = []

    # ---------- A: 原件重传 ----------
    for path, g in sorted(groups.items(), key=lambda x: -x[1]["frags"]):
        titles = sorted(set(g["titles"]),
                        key=lambda t: (bool(re.search(r"\.(pdf|docx|xlsx|md|txt)$", t, re.I)), t))
        main_title = titles[0]
        bank = ""
        for t in titles:
            if t in banks:
                bank = banks[t][0] or banks[t][1] or ""
                break
        bank = bank or "standards"
        size = os.path.getsize(path) if os.path.exists(path) else 0

        ids = []
        for t in titles:
            ids += frag_ids(cur, t)
        if not ids:
            print(f"\n[跳过] 无 active 碎片: {main_title[:50]}")
            continue

        print(f"\n>>> [A] {main_title[:56]}")
        print(f"    原件 {size:,} B  bank={bank}  碎片 {len(ids)}  → 标题组 {titles}")

        if args.skip_upload:
            new_id = find_new_doc(cur, main_title)
            if not new_id:
                print("    [跳过] 无既有新 doc，--skip-upload 下不动")
                continue
        else:
            if not os.path.exists(path):
                print(f"    [FAIL] 原件不存在: {path}")
                failures.append((main_title, "原件缺失"))
                continue
            with open(path, "rb") as f:
                payload = f.read()
            try:
                resp = upload(token, payload, clean_name(path), main_title, bank)
            except Exception as e:  # noqa: BLE001
                print(f"    [FAIL] 上传失败: {e}")
                failures.append((main_title, f"上传失败: {e}"))
                continue
            st = poll(token, resp.get("task_id", ""))
            if st.get("status") not in ("done", "completed", "success"):
                print(f"    [FAIL] 任务未成功: {st.get('status')}")
                failures.append((main_title, f"任务 {st.get('status')}"))
                continue
            new_id = find_new_doc(cur, main_title)
            if not new_id:
                print("    [FAIL] 库中未找到新 doc")
                failures.append((main_title, "新 doc 未落库"))
                continue
            print(f"    新 doc = {new_id[:8]}")

        pgc = supersede(dsn, ids, new_id, "p1_merge")
        for fid in ids:
            cur.execute("UPDATE documents SET status='superseded', superseded_by=?, "
                        "stale_at=?, stale_reason='p1_merge' WHERE doc_id=? AND status='active'",
                        (new_id, now, fid))
        con.commit()
        stats["A"] += 1
        print(f"    pg 清 {pgc} 向量 / SQLite 撤销 {len(ids)} 碎片 ✓")

    # ---------- B: 备份恢复 ----------
    for r in [x for x in rows if x["letter"] == "B"]:
        t = r["title"]
        ids = frag_ids(cur, t)
        print(f"\n>>> [B] {t[:56]}  碎片 {len(ids)}")
        if not ids:
            print("    [跳过] 无 active 碎片")
            continue
        if args.skip_upload:
            new_id = find_new_doc(cur, t)
            if not new_id:
                print("    [跳过] 无既有新 doc")
                continue
        else:
            info = export_from_backup(t)
            if not info:
                failures.append((t, "备份无正文"))
                print("    [FAIL] 备份中无正文")
                continue
            print(f"    导出 {info['chars']} 字符  bank={info['bank']}")
            try:
                resp = upload(token, open(info["path"], "rb").read(),
                              os.path.basename(info["path"]), info["title"],
                              info["bank"] or "general")
            except Exception as e:  # noqa: BLE001
                failures.append((t, f"上传失败: {e}"))
                print(f"    [FAIL] 上传失败: {e}")
                continue
            st = poll(token, resp.get("task_id", ""))
            if st.get("status") not in ("done", "completed", "success"):
                failures.append((t, f"任务 {st.get('status')}"))
                print(f"    [FAIL] 任务未成功: {st.get('status')}")
                continue
            new_id = find_new_doc(cur, info["title"]) or find_new_doc(cur, t)
            if not new_id:
                failures.append((t, "新 doc 未落库"))
                print("    [FAIL] 新 doc 未落库")
                continue
            print(f"    新 doc = {new_id[:8]}  ({info['chars']} 字符)")

        pgc = supersede(dsn, ids, new_id, "p1_merge")
        for fid in ids:
            cur.execute("UPDATE documents SET status='superseded', superseded_by=?, "
                        "stale_at=?, stale_reason='p1_merge' WHERE doc_id=? AND status='active'",
                        (new_id, now, fid))
        con.commit()
        stats["B"] += 1
        print(f"    pg 清 {pgc} 向量 / SQLite 撤销 {len(ids)} 碎片 ✓")

    # ---------- C: 仅清碎片 ----------
    for r in [x for x in rows if x["letter"] == "C"]:
        t = r["title"]
        ids = frag_ids(cur, t)
        print(f"\n>>> [C] {t[:56]}  碎片 {len(ids)}")
        if not ids:
            continue
        better = find_better_doc(cur, t)
        if not better:
            failures.append((t, "无 manual 正主"))
            print("    [FAIL] 未找到 manual 正主，暂不动")
            continue
        pgc = supersede(dsn, ids, better, "p1_merge")
        for fid in ids:
            cur.execute("UPDATE documents SET status='superseded', superseded_by=?, "
                        "stale_at=?, stale_reason='p1_merge' WHERE doc_id=? AND status='active'",
                        (better, now, fid))
        con.commit()
        stats["C"] += 1
        print(f"    → superseded_by={better[:8]}  pg 清 {pgc} / 撤销 {len(ids)} ✓")

    # ---------- D / E: 撤销 ----------
    for r in [x for x in rows if x["letter"] in ("D", "E")]:
        t = r["title"]
        ids = frag_ids(cur, t)
        if not ids:
            continue
        reason = "p1_exclude" if r["letter"] == "D" else "p1_junk"
        print(f"\n>>> [{r['letter']}] {t[:56]}  碎片 {len(ids)}")
        pgc = supersede(dsn, ids, None, reason)
        for fid in ids:
            cur.execute("UPDATE documents SET status='superseded', superseded_by=NULL, "
                        "stale_at=?, stale_reason=? WHERE doc_id=? AND status='active'",
                        (now, reason, fid))
        con.commit()
        stats[r["letter"]] += 1
        print(f"    pg 清 {pgc} / 撤销 {len(ids)} ✓")

    con.close()

    print("\n=== 汇总 ===")
    for k in sorted(stats):
        print(f"   {k}: {stats[k]} 组")
    if failures:
        print("\n=== 失败清单 ===")
        for t, why in failures:
            print(f"   [{why}] {t[:70]}")
    print("\n验证: python3 /tmp/p1_final_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
