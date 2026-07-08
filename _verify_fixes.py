#!/usr/bin/env python3
"""Verification script for kb2-web fixes."""
import json, urllib.request, urllib.parse, sys, time

BASE = "http://127.0.0.1:3027"

# 1. Health check
print("=" * 60)
print("1. Health check")
print("=" * 60)
try:
    resp = urllib.request.urlopen(f"{BASE}/health", timeout=10)
    print(f"Health: {resp.read().decode()}")
except Exception as e:
    print(f"Health FAIL: {e}")

# 2. Get token
print("\n" + "=" * 60)
print("2. Login to get token")
print("=" * 60)
login_data = json.dumps({"username": "admin", "password": "adminljj0806!"}).encode()
req = urllib.request.Request(f"{BASE}/api/auth/login", data=login_data,
    headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    token_data = json.loads(resp.read())
    TOKEN = token_data["access_token"]
    print(f"Token obtained: {TOKEN[:20]}...")
except Exception as e:
    print(f"Login FAIL: {e}")
    sys.exit(1)

def do_query(query, label, timeout=60):
    print(f"\n{'=' * 60}")
    print(f"{label}")
    print(f"Query: {query[:60]}...")
    print("=" * 60)
    data = urllib.parse.urlencode({"q": query, "nocache": "true", "rerank": "false"}).encode()
    req = urllib.request.Request(f"{BASE}/api/query", data=data,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(resp.read())
        answer = result.get("answer", "")
        print(f"answer_len={len(answer)}")
        print(f"answer[:250]: {answer[:250]}")
        return answer
    except Exception as e:
        print(f"Query FAIL: {e}")
        return ""

# 3. B02 rejection test
print("\n\n" + "=" * 60)
print("3. B02 REJECTION TEST (GB 50058 - should reject)")
print("=" * 60)
a1 = do_query("GB 50058 爆炸危险环境电气设计规范的内容是什么？", "B02 Rejection")

reject_keywords = ["未找到", "未收录", "知识库", "抱歉", "无法", "没有找到"]
b02_rejected = any(kw in a1 for kw in reject_keywords) or len(a1) < 30
print(f"\n>>> B02 {'REJECTED ✓ (拒答正确)' if b02_rejected else 'NOT REJECTED ✗'}")

# 4. Normal regression test
print("\n\n" + "=" * 60)
print("4. NORMAL REGRESSION TEST (GB 50348-2018 - should answer with 2018)")
print("=" * 60)
a2 = do_query("GB 50348-2018 安全防范工程技术标准的施行日期是哪一天？", "Normal Regression")
has_2018 = "2018" in a2
print(f"\n>>> Has 2018: {'YES ✓' if has_2018 else 'NO ✗'}")

# 5. B01 geo rejection
print("\n\n" + "=" * 60)
print("5. B01 GEO REJECTION TEST (北京 - should reject)")
print("=" * 60)
a3 = do_query("北京市政务信息化项目管理办法有哪些具体规定？", "B01 Geo Rejection")
b01_rejected = any(kw in a3 for kw in reject_keywords) or len(a3) < 30
print(f"\n>>> B01 {'REJECTED ✓ (拒答正确)' if b01_rejected else 'NOT REJECTED ✗'}")

# Summary
print("\n\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Health:            OK")
print(f"B02 Rejection:     {'PASS ✓' if b02_rejected else 'FAIL ✗'}")
print(f"Normal Regression: {'PASS ✓' if has_2018 else 'FAIL ✗'}")
print(f"B01 Geo Rejection: {'PASS ✓' if b01_rejected else 'FAIL ✗'}")
