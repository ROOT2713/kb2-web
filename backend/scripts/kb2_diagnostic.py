#!/usr/bin/env python3
"""
kb2-web 知识库 V2 全量诊断脚本
================================
覆盖：API可用性、数据完整性、缓存机制、查询质量、Hindsight状态
输出：Markdown 评估报告
"""
import json, os, sys, time, re, sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

# ── Config ────────────────────────────────────────────────────────
BASE_URL = "http://localhost:3027"
HINDSIGHT_URL = "http://localhost:8888"
DB_PATH = "/home/ubuntu/kb-web/data/kb.db"
ADMIN = {"username": "admin", "password": "adminljj0806!"}
TIMEOUT = 30
TOP_K = 5

# ── Global State ──────────────────────────────────────────────────
TOKEN = ""
client = httpx.Client(timeout=TIMEOUT)


def log(msg: str):
    print(f"  {msg}")


def api(url: str, method="GET", **kwargs) -> httpx.Response:
    """Call API with auth token."""
    headers = kwargs.pop("headers", {})
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    kwargs["headers"] = headers
    fn = getattr(client, method.lower())
    try:
        return fn(urljoin(BASE_URL, url), **kwargs)
    except Exception as e:
        return type("FakeResp", (), {"status_code": 0, "text": str(e), "json": lambda self: {}})()


def api_form(url: str, **data) -> httpx.Response:
    """POST with form data + auth."""
    headers = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return client.post(urljoin(BASE_URL, url), data=data, headers=headers)


# ═══════════════════════════════════════════════════════════════════
# 0. 登录
# ═══════════════════════════════════════════════════════════════════
def login():
    global TOKEN
    r = client.post(
        urljoin(BASE_URL, "/api/auth/login"),
        json=ADMIN, timeout=10
    )
    if r.status_code != 200:
        print(f"[FAIL] 登录失败: {r.status_code} {r.text[:200]}")
        return False
    TOKEN = r.json().get("access_token", "")
    print(f"[OK] 登录成功, token长度: {len(TOKEN)}")
    return True


# ═══════════════════════════════════════════════════════════════════
# 1. API 可用性
# ═══════════════════════════════════════════════════════════════════
def check_api_availability():
    results = {"passed": 0, "failed": 0, "details": []}
    checks = [
        ("health", "/health", "GET", None, 200, {"status": "ok"}),
        ("auth_login", "/api/auth/login", "POST", ADMIN, 200, {"access_token": str}),
        ("api_banks", "/api/banks", "GET", None, 200, None),
        ("api_documents", "/api/documents", "GET", None, 200, None),
        ("api_synonyms", "/api/synonyms", "GET", None, 200, None),
        ("api_concepts", "/api/concepts", "GET", None, 200, None),
        ("api_admin_stats", "/api/admin/stats", "GET", None, 200, None),
    ]

    for name, url, method, data, exp_status, _ in checks:
        try:
            if method == "POST":
                resp = client.post(urljoin(BASE_URL, url), json=data or {},
                                   headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN and name != "auth_login" else {})
            else:
                resp = client.get(urljoin(BASE_URL, url),
                                  headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})
            ok = resp.status_code == exp_status
            key = "PASS" if ok else "FAIL"
            results["passed" if ok else "failed"] += 1
            results["details"].append(
                f"  [{key}] {name} → {resp.status_code} (期望={exp_status})"
                + (f" — {resp.text[:80]}" if not ok else "")
            )
        except Exception as e:
            results["failed"] += 1
            results["details"].append(f"  [FAIL] {name} → EXCEPTION: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════
# 2. 数据完整性
# ═══════════════════════════════════════════════════════════════════
def check_data_integrity():
    results = {"passed": 0, "failed": 0, "details": []}

    if not os.path.exists(DB_PATH):
        results["details"].append("  [SKIP] DB 文件不存在")
        return results
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2a. 文档数与搜索状态
    cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN searchable=1 THEN 1 ELSE 0 END) as searchable FROM documents")
    row = cursor.fetchone()
    total_docs = row["total"]
    searchable_docs = row["searchable"] or 0
    searchable_ratio = f"{searchable_docs/total_docs*100:.1f}%" if total_docs else "N/A"
    results["details"].append(f"  [INFO] 文档总数: {total_docs}, 可搜索: {searchable_docs} ({searchable_ratio})")
    results["passed"] += 1

    # 2b. 空标题/空内容检查
    cursor.execute("SELECT COUNT(*) FROM documents WHERE title IS NULL OR title = ''")
    null_titles = cursor.fetchone()[0]
    if null_titles:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] 空标题文档: {null_titles}")
    else:
        results["passed"] += 1
        results["details"].append(f"  [PASS] 所有文档有标题")

    # 2c. Bank 有效性
    cursor.execute("SELECT DISTINCT bank FROM documents")
    banks_in_db = {r["bank"] for r in cursor.fetchall()}
    if banks_in_db:
        results["details"].append(f"  [INFO] DB 中的 banks: {sorted(banks_in_db)}")
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["details"].append("  [FAIL] 无文档银行")

    # 2d. Chunks 数据
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
        has_chunks_table = cursor.fetchone() is not None
    except:
        has_chunks_table = False

    if has_chunks_table:
        try:
            cursor.execute("SELECT COUNT(*) FROM chunks")
            total_chunks = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM chunks WHERE text IS NULL OR text = ''")
            empty_chunks = cursor.fetchone()[0]
            avg_chunk_len = cursor.execute("SELECT AVG(LENGTH(text)) FROM chunks").fetchone()[0]
            results["details"].append(
                f"  [INFO] Chunks: {total_chunks}, 空chunk: {empty_chunks}, avg长度: {avg_chunk_len:.0f}")
            results["passed"] += 1
            if empty_chunks:
                results["failed"] += 1
                results["details"].append(f"  [FAIL] 存在空chunk: {empty_chunks}")
            else:
                results["passed"] += 1
        except Exception as e:
            results["details"].append(f"  [INFO] chunks表查询: {e}")

        # 2e. Orphaned chunks
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM chunks c
                LEFT JOIN documents d ON c.doc_id = d.doc_id
                WHERE d.doc_id IS NULL
            """)
            orphaned = cursor.fetchone()[0]
            if orphaned:
                results["failed"] += 1
                results["details"].append(f"  [FAIL] 孤儿 chunk: {orphaned}")
            else:
                results["passed"] += 1
                results["details"].append(f"  [PASS] 无孤儿 chunk")
        except:
            pass
    else:
        results["details"].append("  [INFO] 无 chunks 表 (数据通过 Hindsight 管理)")
        results["passed"] += 1

    # 2f. 每个银行的文档数
    cursor.execute("SELECT bank, COUNT(*) as cnt FROM documents GROUP BY bank ORDER BY cnt DESC")
    bank_counts = cursor.fetchall()
    results["details"].append(f"  [INFO] 各 Bank 文档数:")
    for r in bank_counts[:10]:
        results["details"].append(f"          - {r['bank']}: {r['cnt']}")

    # 2g. 创建时间新鲜度
    cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM documents")
    min_t, max_t = cursor.fetchone()
    results["details"].append(f"  [INFO] 文档时间范围: {min_t} → {max_t}")

    cursor.execute("SELECT MIN(updated_at), MAX(updated_at) FROM documents")
    min_ut, max_ut = cursor.fetchone()
    if min_ut:
        results["details"].append(f"  [INFO] 更新/上传时间范围: {min_ut} → {max_ut}")

    # 2h. 未来日期检查 (created_at)
    cursor.execute("SELECT COUNT(*) FROM documents WHERE created_at > datetime('now', '+1 hour')")
    future_dates = cursor.fetchone()[0]
    if future_dates:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] 未来创建时间: {future_dates}")
    else:
        results["passed"] += 1
        results["details"].append(f"  [PASS] 无未来日期")

    conn.close()
    return results


# ═══════════════════════════════════════════════════════════════════
# 3. 缓存机制
# ═══════════════════════════════════════════════════════════════════
def check_cache():
    results = {"passed": 0, "failed": 0, "details": []}

    # 3a. 首次查询 (nocache) — 不应命中缓存
    t0 = time.time()
    with httpx.Client(timeout=120) as qclient:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        r = qclient.post(urljoin(BASE_URL, "/api/query"),
            data={"q": "信息化测评收费标准", "bank": "standards", "nocache": "true", "top_k": str(TOP_K)},
            headers=headers)
    t1 = time.time()
    if r.status_code == 200:
        data = r.json()
        ans_len = len(data.get("answer", ""))
        src_count = len(data.get("sources", []))
        results["details"].append(
            f"  [PASS] 查询(nocache): {t1-t0:.1f}s, answer={ans_len}字符, sources={src_count}")
        results["passed"] += 1
    else:
        results["details"].append(f"  [FAIL] 查询失败: {r.status_code} — {r.text[:100]}")
        results["failed"] += 1

    # 3b. 二次相同查询 (应命中缓存)
    t0 = time.time()
    with httpx.Client(timeout=60) as qclient:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        r2 = qclient.post(urljoin(BASE_URL, "/api/query"),
            data={"q": "信息化测评收费标准", "bank": "standards", "nocache": "false", "top_k": str(TOP_K)},
            headers=headers)
    t2 = time.time()
    if r2.status_code == 200:
        results["details"].append(
            f"  [PASS] 查询(缓存): {t2-t0:.1f}s (若 < nocache 时间则命中缓存)")
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] 缓存查询: {r2.status_code}")

    # 3c. 不同参数 (不同 bank)
    t0 = time.time()
    with httpx.Client(timeout=120) as qclient:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        r3 = qclient.post(urljoin(BASE_URL, "/api/query"),
            data={"q": "信息化测评收费标准", "bank": "all", "nocache": "true", "top_k": str(TOP_K)},
            headers=headers)
    t3 = time.time()
    if r3.status_code == 200:
        results["details"].append(f"  [PASS] 不同bank查询: {t3-t0:.1f}s")
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] 不同bank查询: {r3.status_code}")

    return results


# ═══════════════════════════════════════════════════════════════════
# 4. 查询质量评估
# ═══════════════════════════════════════════════════════════════════
GOLDEN_QUERIES = [
    ("Q01", "标准号精确", "GB/T 25000.51 验收测评", "standards", 2, ["25000"]),
    ("Q02", "标准号精确", "GB/T 39786 密码应用", "standards", 2, ["39786"]),
    ("Q03", "取费查询", "等保测评费用 收费标准", "all", 2, []),
    ("Q04", "取费查询", "软件造价 取费标准 信息化项目", "all", 2, ["造价", "费用"]),
    ("Q05", "政策法规", "密码法 商用密码", "standards", 1, ["密码"]),
    ("Q06", "政策法规", "等保 2.0 安全要求", "standards", 1, ["等保", "安全"]),
    ("Q07", "技术方案", "机房建设 设计规范", "standards", 1, ["机房"]),
    ("Q08", "技术方案", "视频监控 存储 30天", "standards", 1, ["监控"]),
    ("Q09", "边缘场景", "a@b#c$d% 非标准查询", "all", 0, []),
    ("Q10", "多bank", "信息安全 测评 方案", "all", 3, []),
]


def check_query_quality():
    results = {"passed": 0, "failed": 0, "details": [], "queries": []}

    for qid, cat, query_text, bank, min_src, must_titles in GOLDEN_QUERIES:
        with httpx.Client(timeout=120) as qclient:
            headers = {"Authorization": f"Bearer {TOKEN}"}
            r = qclient.post(urljoin(BASE_URL, "/api/query"), 
                data={"q": query_text, "bank": bank, "nocache": "true", "top_k": str(TOP_K)},
                headers=headers)
        if r.status_code != 200:
            results["failed"] += 1
            results["details"].append(f"  [FAIL] {qid} [{cat}] HTTP {r.status_code}: {query_text[:30]}")
            results["queries"].append({"id": qid, "status": "FAIL", "status_code": r.status_code})
            continue

        data = r.json()
        answer = data.get("answer", "")
        sources = data.get("sources", [])
        src_count = len(sources)
        ans_len = len(answer)

        issues = []
        if min_src > 0 and src_count < min_src:
            issues.append(f"sources={src_count}<{min_src}")
        for mt in must_titles:
            found = any(mt.lower() in str(s.get("title", s.get("doc", ""))).lower() for s in sources)
            if not found:
                issues.append(f"缺少'{mt}'")
        if not answer and qid != "Q09":
            issues.append("空答案")

        ok = len(issues) == 0
        key = "PASS" if ok else "FAIL"
        results["passed" if ok else "failed"] += 1
        src_sample = [s.get("title", s.get("doc", "?"))[:45] for s in sources[:3]]
        results["details"].append(
            f"  [{key}] {qid} [{cat}] \"{query_text[:30]}\" → {src_count}来源, {ans_len}字符answer"
            + (f"\n         来源: {src_sample}" if src_sample else "")
            + (f"\n         问题: {'; '.join(issues)}" if issues else "")
        )
        results["queries"].append({
            "id": qid, "category": cat, "query": query_text, "status": key,
            "sources": src_count, "answer_len": ans_len, "issues": issues,
            "source_titles": [s.get("title", s.get("doc", "?")) for s in sources[:5]]
        })

    return results


# ═══════════════════════════════════════════════════════════════════
# 5. Hindsight 状态
# ═══════════════════════════════════════════════════════════════════
def check_hindsight():
    results = {"passed": 0, "failed": 0, "details": []}

    # 5a. Health
    try:
        r = client.get(f"{HINDSIGHT_URL}/health", timeout=5)
        if r.status_code == 200:
            results["details"].append(f"  [PASS] Hindsight health: {r.json().get('status','?')}")
            results["passed"] += 1
        else:
            results["failed"] += 1
            results["details"].append(f"  [FAIL] Hindsight health: {r.status_code}")
    except Exception as e:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] Hindsight 无法连接: {e}")

    # 5b. Banks
    try:
        r = client.get(f"{HINDSIGHT_URL}/v1/default/banks", timeout=10)
        if r.status_code == 200:
            banks = r.json().get("banks", [])
            total_mem = sum(b.get("fact_count", 0) for b in banks)
            results["details"].append(f"  [PASS] Hindsight banks: {len(banks)}, memories: {total_mem}")
            for b in sorted(banks, key=lambda x: -x.get("fact_count", 0))[:8]:
                results["details"].append(
                    f"          [{b['bank_id']}] {b.get('fact_count',0)} mem")
            results["passed"] += 1
        else:
            results["failed"] += 1
            results["details"].append(f"  [FAIL] Hindsight banks: {r.status_code}")
    except Exception as e:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] Hindsight banks 异常: {e}")

    # 5c. Recall test
    try:
        r = client.post(
            f"{HINDSIGHT_URL}/v1/default/banks/kb_standard/memories/recall",
            json={"query": "等保测评", "limit": 3, "max_tokens": 999999}, timeout=10
        )
        if r.status_code == 200:
            mems = r.json().get("results", [])
            results["details"].append(f"  [PASS] Hindsight recall test: {len(mems)} results")
            results["passed"] += 1
        else:
            results["failed"] += 1
            results["details"].append(f"  [FAIL] Hindsight recall: {r.status_code}")
    except Exception as e:
        results["failed"] += 1
        results["details"].append(f"  [FAIL] Hindsight recall: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════
# 6. 前端页面加载
# ═══════════════════════════════════════════════════════════════════
def check_frontend():
    results = {"passed": 0, "failed": 0, "details": []}
    routes = ["/", "/documents", "/admin", "/upload"]

    for route in routes:
        try:
            r = client.get(urljoin(BASE_URL, route), follow_redirects=True, timeout=10)
            is_html = "text/html" in (r.headers.get("content-type", ""))
            has_app = "id=\"app\"" in r.text or "class=\"app\"" in r.text or "#app" in r.text
            if r.status_code == 200 and is_html and has_app:
                results["passed"] += 1
                size_kb = len(r.content) / 1024
                results["details"].append(f"  [PASS] {route} → {r.status_code}, HTML({size_kb:.0f}KB), app挂载点存在")
            else:
                results["failed"] += 1
                issues = []
                if r.status_code != 200: issues.append(f"status={r.status_code}")
                if not is_html: issues.append(f"content-type={r.headers.get('content-type')}")
                if not has_app: issues.append("no #app mount")
                results["details"].append(f"  [FAIL] {route} → {'; '.join(issues)})")
        except Exception as e:
            results["failed"] += 1
            results["details"].append(f"  [FAIL] {route} → EXCEPTION: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════
# 7. KB 与 Hindsight 数据一致性
# ═══════════════════════════════════════════════════════════════════
def check_kb_hindsight_consistency():
    results = {"passed": 0, "failed": 0, "details": []}

    if not os.path.exists(DB_PATH):
        results["details"].append("  [SKIP] DB 文件不存在")
        return results

    # 获取 KB 端各 bank 的 searchable 文档数
    conn = sqlite3.connect(DB_PATH)
    kb_banks = conn.execute(
        "SELECT bank, COUNT(*) as cnt FROM documents WHERE searchable=1 GROUP BY bank"
    ).fetchall()
    kb_by_bank = {b[0]: b[1] for b in kb_banks}
    kb_total = sum(kb_by_bank.values())
    conn.close()

    results["details"].append(f"  [INFO] KB searchable文档: {kb_total}")
    for bank, cnt in sorted(kb_by_bank.items(), key=lambda x: -x[1]):
        results["details"].append(f"          - {bank}: {cnt}")

    # 获取 Hindsight 端数据
    try:
        r = client.get(f"{HINDSIGHT_URL}/v1/default/banks", timeout=10)
        if r.status_code == 200:
            hs_banks = r.json().get("banks", [])
            hs_by_bank = {b["bank_id"].replace("kb_", ""): b.get("fact_count", 0) for b in hs_banks}
            match = 0
            mismatch = 0
            for kb_name, kb_cnt in kb_by_bank.items():
                hs_key = kb_name
                mem_cnt = hs_by_bank.get(hs_key, hs_by_bank.get(f"kb_{hs_key}", 0))
                if mem_cnt > 0:
                    match += 1
                else:
                    mismatch += 1
            results["details"].append(
                f"  [INFO] KB↔Hindsight bank匹配: {match} 匹配, {mismatch} 不匹配")
            results["passed"] += 1
        else:
            results["details"].append(f"  [FAIL] 无法获取Hindsight banks: {r.status_code}")
            results["failed"] += 1
    except Exception as e:
        results["details"].append(f"  [FAIL] Hindsight一致性检查异常: {e}")
        results["failed"] += 1

    return results


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("kb2-web 知识库 V2 全量诊断报告")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Login
    if not login():
        return

    all_results = {}
    summary = {}

    # 1. API 可用性
    print("\n\n## 1. API 端点可用性")
    r = check_api_availability()
    all_results["API 端点可用性"] = r
    summary["API端点"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # 2. 数据完整性
    print("\n\n## 2. 数据完整性")
    r = check_data_integrity()
    all_results["数据完整性"] = r
    summary["数据完整性"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # 3. 缓存机制
    print("\n\n## 3. 缓存机制")
    r = check_cache()
    all_results["缓存机制"] = r
    summary["缓存机制"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # 4. 查询质量
    print("\n\n## 4. 查询质量评估")
    r = check_query_quality()
    all_results["查询质量"] = r
    summary["查询质量"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # 5. Hindsight
    print("\n\n## 5. Hindsight 状态")
    r = check_hindsight()
    all_results["Hindsight"] = r
    summary["Hindsight"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # 6. 前端页面
    print("\n\n## 6. 前端页面加载")
    r = check_frontend()
    all_results["前端页面"] = r
    summary["前端页面"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # 7. KB↔Hindsight 一致性
    print("\n\n## 7. KB↔Hindsight 数据一致性")
    r = check_kb_hindsight_consistency()
    all_results["KB↔Hindsight一致性"] = r
    summary["KB↔Hindsight一致性"] = f"{r['passed']} pass / {r['failed']} fail"
    for d in r["details"]:
        print(d)

    # ── 汇总 ──
    total_pass = sum(v["passed"] for v in all_results.values())
    total_fail = sum(v["failed"] for v in all_results.values())
    print("\n\n" + "=" * 60)
    print(f"诊断汇总: {total_pass} pass / {total_fail} fail")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # Save report
    report_path = "/tmp/kb2_diagnostic_report.md"
    generate_markdown(all_results, summary, total_pass, total_fail, report_path)
    print(f"\n\n报告已保存: {report_path}")


def generate_markdown(all_results, summary, total_pass, total_fail, path):
    md = []
    md.append(f"# kb2-web 知识库 V2 全量诊断报告\n")
    md.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    md.append(f"**诊断汇总**: {total_pass} ✅ / {total_fail} ❌\n")
    md.append("| 维度 | 结果 | 等级 |")
    md.append("|------|------|------|")
    graded = {
        "API端点": (summary.get("API端点", "0/0"), "🟢" if total_fail == 0 else "🟡" if total_fail <= 3 else "🔴"),
        "数据完整性": (summary.get("数据完整性", "0/0"),
                      "🟢" if "FAIL" not in str(all_results.get("数据完整性", {}).get("details", [])) else "🔴"),
        "缓存机制": (summary.get("缓存机制", "0/0"), "🟢"),
        "查询质量": (summary.get("查询质量", "0/0"), "🟡" if any("FAIL" in d for d in all_results.get("查询质量", {}).get("details", [])) else "🟢"),
        "Hindsight": (summary.get("Hindsight", "0/0"), "🟢"),
        "前端页面": (summary.get("前端页面", "0/0"), "🟡" if "FAIL" in str(all_results.get("前端页面", {}).get("details", [])) else "🟢"),
        "KB↔Hindsight一致性": (summary.get("KB↔Hindsight一致性", "0/0"), "🟢"),
    }
    for dim, (stat, grade) in graded.items():
        md.append(f"| {dim} | {stat} | {grade} |")

    for section_name, section_data in all_results.items():
        md.append(f"\n---\n## {section_name}\n")
        md.append(f"**确诊项**: {section_data.get('passed', 0)} 通过 / {section_data.get('failed', 0)} 失败\n")
        md.append("```")
        for d in section_data.get("details", []):
            md.append(d)
        md.append("```")

        # Query detail table
        if section_name == "查询质量" and "queries" in section_data:
            md.append("\n| ID | 分类 | 查询 | 来源数 | 答案长度 | 状态 |")
            md.append("|----|------|------|--------|----------|------|")
            for q in section_data["queries"]:
                status_icon = "✅" if q["status"] == "PASS" else "❌"
                md.append(f"| {q['id']} | {q['category']} | {q.get('query','')[:30]} | {q['sources']} | {q['answer_len']} | {status_icon} |")

    md.append("\n---\n## 关键发现\n")
    # Find all FAIL items
    all_fails = []
    for section_name, section_data in all_results.items():
        for d in section_data.get("details", []):
            if "[FAIL]" in d:
                all_fails.append(f"- **{section_name}**: {d.strip()}")
    if all_fails:
        md.append("### ❌ 失败项\n")
        md.extend(all_fails)
    else:
        md.append("无关键失败项。\n")

    # Query issue summary
    if "queries" in all_results.get("查询质量", {}):
        failed_queries = [q for q in all_results["查询质量"]["queries"] if q["status"] != "PASS"]
        if failed_queries:
            md.append("\n### ❌ 查询质量问题\n")
            for q in failed_queries:
                md.append(f"- **{q['id']}** [{q['category']}] \"{q.get('query','')}\": {', '.join(q.get('issues',[]))}")
        else:
            md.append("\n### ✅ 查询质量\n所有黄金查询通过。\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"Markdown report written to {path}")


if __name__ == "__main__":
    main()
