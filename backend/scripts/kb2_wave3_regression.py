#!/usr/bin/env python3
"""Quick regression test — Wave 1+2 core scenarios + representative sample."""
import sys, json, time, requests

BASE = "http://127.0.0.1:3027"
r = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "adminljj0806!"}, timeout=10)
TOKEN = r.json()["access_token"]

TESTS = [
    # ── S series: Wave 1+2 修复回归（拒答）──
    ("S01: B02 GB 50058拒答", "GB 50058 爆炸危险环境电气设计规范的内容是什么？",
     lambda a: any(w in a[:500] for w in ["未找到","未收录","不能提供","未包含","未能找到"])),
    ("S02: B01 北京拒答", "北京市政务信息化项目管理办法有哪些具体规定？",
     lambda a: any(w in a[:500] for w in ["未找到","未收录","未包含","未涵盖","北京"])),
    ("S03: GDPR拒答", "GDPR（通用数据保护条例）对个人信息保护有什么要求？",
     lambda a: any(w in a[:500] for w in ["未找到","未收录","未包含"])),
    ("S04: 深圳拒答", "深圳市政务信息化项目管理办法的具体内容是什么？",
     lambda a: any(w in a[:500] for w in ["未找到","未收录","未包含"])),
    ("S05: 浙江拒答", "浙江省政务信息化项目管理实施细则有哪些规定？",
     lambda a: any(w in a[:500] for w in ["未找到","未收录","未包含"])),

    # ── GB 50348 回归（Wave 1 修复后不应误拒）──
    ("50348回归", "GB 50348-2018 安全防范工程技术标准的施行日期是哪一天？",
     lambda a: "2018" in a and len(a) > 100),

    # ── D系列回归（多轮域锁定/跨域跳跃）──
    ("D09方法论", "软件造价评估实施规程中，功能点方法有哪些主要原则？",
     lambda a: len(a) > 500 and "功能点" in a),
    ("D09标准", "GB/T 36964-2018 软件工程 软件开发成本度量规范的主要内容是什么？",
     lambda a: "36964" in a and len(a) > 300),

    # ── H系列（政务信息化新增）──
    ("H01广州管理办法", "广州市政务信息化项目管理办法有哪些关键条款？",
     lambda a: "广州" in a and "管理" in a and len(a) > 200),
    ("H02验收测评费", "政务信息化项目验收测评费取费标准是什么？",
     lambda a: any(w in a for w in ["万","元","费用"]) and len(a) > 200),
    ("H03功能点方法", "软件造价评估实施规程中，功能点方法有哪些主要原则？",
     lambda a: "功能点" in a and len(a) > 300),
    ("H04 36964", "GB/T 36964-2018 软件工程 软件开发成本度量规范的主要内容是什么？",
     lambda a: "36964" in a and len(a) > 300),

    # ── Z系列（安全/边界）──
    ("Z03 50348", "GB 50348-2018 安全防范工程技术标准的施行日期是哪一天？",
     lambda a: "2018" in a and len(a) > 80),
    ("Z04 510万费", "510万信息化项目验收测评费大致是多少？",
     lambda a: any(w in a for w in ["万","元","费用"]) and len(a) > 200),

    # ── 管理类关键回归──
    ("A01端子", "接线端子和接地端子有什么不同？",
     lambda a: len(a) > 200),
    ("C01接地电阻", "机柜的接地电阻是多少？",
     lambda a: "接地电阻" in a and len(a) > 100),
    ("C10等保周期", "等保测评要求多久做一次？",
     lambda a: any(w in a for w in ["一年","1年","每年"]) and len(a) > 100),
    ("F07 50万费", "一个50万元的弱电项目验收测评费要多少钱？",
     lambda a: "万" in a and len(a) > 100),
]

results = []
for label, question, check_fn in TESTS:
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/query", headers={"Authorization": f"Bearer {TOKEN}"},
                         data={"q": question, "nocache": "true", "rerank": "false"}, timeout=180)
        d = r.json()
        ans = d.get("answer", "")
        src_count = len(d.get("sources", []))
        passed = check_fn(ans)
    except Exception as e:
        ans = ""
        src_count = 0
        passed = False
    elapsed = time.time() - t0
    status = "✅" if passed else "❌"
    results.append((label, status, len(ans), src_count, elapsed, ans[:120] if not passed else ""))
    print(f"  {status} {label}: {len(ans)}字 {elapsed:.0f}s src={src_count}")
    if not passed:
        print(f"     首120字: {ans[:120]}")

passed = sum(1 for _, s, _, _, _, _ in results if s == "✅")
total = len(results)
print(f"\n{'='*50}")
print(f"回归测试: {passed}/{total} ({round(passed/total*100,1)}%)")
if passed < total:
    print("\nFAILURES:")
    for label, status, length, src, elapsed, preview in results:
        if status == "❌":
            print(f"  ❌ {label}: {length}字 {elapsed:.0f}s src={src}")
            print(f"     {preview}")
