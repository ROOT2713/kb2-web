#!/usr/bin/env python3
"""Fixed regression — proper rejection detection."""
import sys, json, time, requests

BASE = "http://127.0.0.1:3027"
r = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "adminljj0806!"}, timeout=10)
TOKEN = r.json()["access_token"]

# Rejection phrases (actual rejection signal)
REJECT_PHRASES = ["未找到","未收录","未包含","未能找到","无法回答","没有找到","不能提供","未涉及","未涵盖","未覆盖"]
# Content signal (too much content = not rejected)
def is_rejected(ans):
    for p in REJECT_PHRASES:
        if p in ans[:800]:
            return True
    return False

TESTS = [
    # ── S系列: 拒答回归 ──
    ("S01 B02 GB 50058", "GB 50058 爆炸危险环境电气设计规范的内容是什么？", is_rejected),
    ("S02 B01 北京", "北京市政务信息化项目管理办法有哪些具体规定？", is_rejected),
    ("S03 GDPR", "GDPR（通用数据保护条例）对个人信息保护有什么要求？", is_rejected),
    ("S04 深圳", "深圳市政务信息化项目管理办法的具体内容是什么？", is_rejected),
    ("S05 浙江", "浙江省政务信息化项目管理实施细则有哪些规定？", is_rejected),
    # ── 核心回归 ──
    ("50348施行日", "GB 50348-2018 安全防范工程技术标准的施行日期是哪一天？",
     lambda a: "2018" in a and len(a) > 100),
    ("D09 跨域-标准", "GB/T 36964-2018 软件工程 软件开发成本度量规范的主要内容是什么？",
     lambda a: "36964" in a and len(a) > 300),
    ("广州管理办法", "广州市政务信息化项目管理办法有哪些关键条款？",
     lambda a: "广州" in a and len(a) > 200),
    ("验收测评费", "政务信息化项目验收测评费取费标准是什么？",
     lambda a: any(w in a for w in ["万","元","费用"]) and len(a) > 200),
    ("功能点方法", "软件造价评估实施规程中，功能点方法有哪些主要原则？",
     lambda a: "功能点" in a and len(a) > 300),
    ("36964", "GB/T 36964-2018 软件工程 软件开发成本度量规范的主要内容是什么？",
     lambda a: "36964" in a and len(a) > 300),
    ("510万费", "510万信息化项目验收测评费大致是多少？",
     lambda a: any(w in a for w in ["万","元"]) and len(a) > 200),
    ("机柜接地电阻", "机柜的接地电阻是多少？",
     lambda a: "接地电阻" in a and len(a) > 100),
    ("等保周期", "等保测评要求多久做一次？",
     lambda a: any(w in a for w in ["一年","1年","每年"]) and len(a) > 100),
    ("50万", "一个50万元的弱电项目验收测评费要多少钱？",
     lambda a: "万" in a and len(a) > 100),
]

print(f"{'测试':<20} {'状态':<6} {'字数':<6} {'来源':<5} {'耗时':<5}")
print("-"*50)
results = []
for label, question, check_fn in TESTS:
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/query", headers={"Authorization": f"Bearer {TOKEN}"},
                         data={"q": question, "nocache": "true", "rerank": "false"}, timeout=180)
        d = r.json()
        ans = d.get("answer","")
        src = len(d.get("sources", []))
        passed = check_fn(ans)
    except Exception as e:
        ans = str(e)
        src = 0
        passed = False
    elapsed = time.time()-t0
    status = "✅" if passed else "❌"
    results.append((label, status, len(ans), src, elapsed))
    print(f"{label:<20} {status:<6} {len(ans):<6} {src:<5} {elapsed:.0f}s")
    if not passed:
        print(f"  {'':<20} 首80: {ans[:80]}")

passed = sum(1 for _, s, _, _, _ in results if s == "✅")
total = len(results)
print(f"\n{'='*50}")
print(f"回归测试: {passed}/{total} ({round(passed/total*100,1)}%)")
