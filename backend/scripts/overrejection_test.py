#!/usr/bin/env python3
"""
kb2-web 过拒/幻觉/术语歧义 专项测试 V2
检测 LLM 在以下场景的表现：
1. 术语歧义（用户用 X 查，文档写 Y）→ LLM 不应说"未找到"
2. LLM 过拒（内容存在但 LLM 说没有）
3. 幻觉检测（LLM 编造不存在的元数据）
4. 跨 chunk 推理（需要组合多个 chunk 的信息）

监测逻辑：
- 真正的"过拒"= 检索命中了相关文档的 chunk，但 LLM 仍然说"未直接规定/未涵盖/未涉及"
- "正确拒绝"= 文档确实没有该内容，LLM 诚实说没有（非过拒）
"""

import subprocess, json, sys, re, time

BASE = "http://127.0.0.1:3027"
TOKEN = None

def login():
    global TOKEN
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE}/api/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"username":"admin","password":"adminljj0806!"}'],
        capture_output=True, text=True, timeout=10
    )
    try:
        data = json.loads(r.stdout)
        TOKEN = data["access_token"]
        return True
    except:
        print(f"❌ Login failed: {r.stdout[:200]}")
        return False

def query(q, nocache=True):
    curl_args = [
        "curl", "-s", "-X", "POST", f"{BASE}/api/query",
        "-H", f"Authorization: Bearer {TOKEN}",
        "--data-urlencode", f"q={q}",
    ]
    if nocache:
        curl_args.extend(["--data-urlencode", "nocache=true"])
    r = subprocess.run(curl_args, capture_output=True, text=True, timeout=180)
    try:
        return json.loads(r.stdout)
    except:
        return {"error": f"Parse failed: {r.stdout[:300]}"}

def check_overrejection(name, q, doc_hint, expected_rejection_is_correct=False):
    """
    Check if LLM over-rejects when chunk exists.
    expected_rejection_is_correct=True: LLM saying "not found" IS correct (doc truly lacks it)
    """
    resp = query(q)
    ans = resp.get("answer", "")
    sources = [s.get("doc", "")[:50] for s in resp.get("sources", [])]
    
    has_doc = any(doc_hint in s for s in sources)
    
    # True over-rejection: chunk IS in context but LLM says "not covered"
    rejection_words = ["未直接", "未涉及", "未规定", "未涵盖", "未覆盖"]
    in_rejection = any(w in ans[:300] for w in rejection_words)
    
    issues = []
    
    if has_doc and in_rejection and not expected_rejection_is_correct:
        issues.append(f"TURE_OVERREJECTION (chunk存在但LLM说'未直接规定')")
    elif has_doc and in_rejection and expected_rejection_is_correct:
        pass  # Correct rejection
    elif has_doc:
        pass  # Normal - good behavior
    else:
        issues.append("NO_RELEVANT_SOURCE (文档未命中检索)")
    
    # Hallucination: fabricating chapter numbers not in KB
    if re.search(r"建议[查阅看].*第[五六七八九十\d]+章", ans[:500]):
        issues.append("HALLUCINATION (编造章节建议)")
    
    status = "✅" if not issues else "❌"
    
    print(f"\n  [{status}] {name}")
    print(f"    Sources: {', '.join(sources[:2]) if sources else '[]'}")
    print(f"    Chunk命中: {'✅' if has_doc else '❌'}, 拒绝词: {'✅' if in_rejection else '❌'}")
    print(f"    Issues: {'; '.join(issues) if issues else 'None'}")
    ans_preview = ans[:150].replace('\n', ' ').strip()
    print(f"    A: {ans_preview}...")
    
    return {
        "name": name, "q": q, "issues": issues,
        "has_doc": has_doc, "in_rejection": in_rejection,
        "status": "PASS" if not issues else "FAIL",
        "answer": ans
    }

def main():
    if not login():
        return 1
    
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  kb2-web 过拒/幻觉/术语歧义 专项测试 V2                ║")
    print("╚══════════════════════════════════════════════════════════╝")
    
    results = []
    
    print("\n═══════ Group A: 术语歧义 / LLM过拒检测 ═══════")
    
    # A1: 接地端子 — key issue. GB 16806 has "接线端子" not "接地端子"
    # GB 16806 chunk should be in sources but LLM says "not directly"
    results.append(check_overrejection(
        "A1: 接地端子 → 接线端子+保护接地",
        "GB 16806-2006《消防联动控制系统》对接地端子有什么要求？",
        doc_hint="16806",
        expected_rejection_is_correct=True  # 接地端子≠接线端子，LLM拒绝是正确的
    ))
    
    # A2: 备用电池 — GB 16806 has "蓄电池" sections (idx=9 has 4.1.3.7备用电源及蓄电池)
    results.append(check_overrejection(
        "A2: 备用电池 → 蓄电池",
        "GB 16806-2006 规定备用电池能用多久？",
        doc_hint="16806",
        expected_rejection_is_correct=False
    ))
    
    # A3: 防雷 → 浪涌抗扰度/保护接地 — GB 16806 has these in chunks
    results.append(check_overrejection(
        "A3: 防雷 → 浪涌/保护接地",
        "GB 16806-2006 对防雷有什么要求？",
        doc_hint="16806",
        expected_rejection_is_correct=True  # 防雷≠浪涌抗扰度，概念不同
    ))
    
    # A4: 蜂鸣器 → 音响/报警 — GB 16806 has 音响/报警 signal sections
    results.append(check_overrejection(
        "A4: 蜂鸣器 → 音响/报警信号",
        "GB 16806 里说消防设备蜂鸣器一直响是什么情况？",
        doc_hint="16806",
        expected_rejection_is_correct=False
    ))
    
    # A5: 按钮按不下去 — GB 16806 does NOT have mechanical button specs
    results.append(check_overrejection(
        "A5: 按钮按不下去（正确拒绝）",
        "消防联动控制器的按钮按不下去怎么办，GB 16806 有要求吗？",
        doc_hint="16806",
        expected_rejection_is_correct=True  # Document truly doesn't have this
    ))
    
    # A6: 电源断电 — GB 16806 HAS 4.2.1.2 and 4.1.3.7 power specs
    results.append(check_overrejection(
        "A6: 220V断电 → 主备电源自动转换",
        "GB 16806 规定主电源断电后怎么办？",
        doc_hint="16806",
        expected_rejection_is_correct=False
    ))
    
    print("\n═══════ Group B: 幻觉检测 ═══════")
    
    # B1: 字数 — GB 16806 metadata DOES contain "字数122千字" in chunk idx=2
    results.append(check_overrejection(
        "B1: 元数据（字数/章节数）",
        "GB 16806-2006 全文共有多少字？有几章？",
        doc_hint="16806",
        expected_rejection_is_correct=False  # Metadata exists
    ))
    
    # B2: 第8章 — not in KB, correct to say not available
    results.append(check_overrejection(
        "B2: 不存在的章节（正确拒绝）",
        "GB 16806-2006 第8章讲了什么？",
        doc_hint="16806",
        expected_rejection_is_correct=True  # Chapter 8 truly not in KB
    ))
    
    print("\n═══════ Group C: 跨chunk推理 ═══════")
    
    results.append(check_overrejection(
        "C1: 电源系统总览",
        "GB 16806-2006 对消防联动控制系统的电源系统有什么要求？",
        doc_hint="16806"
    ))
    
    results.append(check_overrejection(
        "C2: 故障报警时限",
        "GB 16806 要求设备多久内检测出故障并报警？",
        doc_hint="16806"
    ))
    
    print("\n═══════ Group D: 回归测试 ═══════")
    
    results.append(check_overrejection(
        "D1(K1): 验收评测费 510万",
        "电子政务软件系统建设规模D=510万元，请问验收评测费是多少？",
        doc_hint="第三部分"
    ))
    
    results.append(check_overrejection(
        "D2(K4): 等保三级费用",
        "电子政务三级等保测评费用是多少？",
        doc_hint="第三部分"
    ))
    
    results.append(check_overrejection(
        "D3(K8): 验收评测费 generic",
        "D=510万元的软件项目，验收评测费怎么算？",
        doc_hint="第三部分"
    ))
    
    results.append(check_overrejection(
        "D4(K9): 通用非计费",
        "GB/T 25000.51-2016 对验收测试流程有什么要求？",
        doc_hint="25000.51"
    ))
    
    results.append(check_overrejection(
        "D5(K10): 东莞设计费",
        "东莞政府投资的6000万元信息化项目，设计费如何计算？",
        doc_hint="东莞"
    ))
    
    results.append(check_overrejection(
        "D6(K11): 非费用不污染",
        "GB/T 2887-2011《计算机场地通用规范》对机房温度有什么要求？",
        doc_hint="2887"
    ))
    
    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    overrejections = [r for r in results if "TURE_OVERREJECTION" in str(r["issues"])]
    hallucinations = [r for r in results if "HALLUCINATION" in str(r["issues"])]
    
    print(f"\n")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  FINAL RESULTS                                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Total: {len(results)}  |  Pass: {passed}  |  Fail: {failed}")
    print(f"  True over-rejections: {len(overrejections)}")
    print(f"  Hallucinations: {len(hallucinations)}")
    
    print(f"\n  ┌──────┬──────────────────────────────────────────┬──────────┐")
    print(f"  │ ID   │ Test                                     │ Status   │")
    print(f"  ├──────┼──────────────────────────────────────────┼──────────┤")
    for r in results:
        tag = "✅" if r["status"] == "PASS" else "❌"
        n = r["name"][:36]
        print(f"  │ {n:36s} │ {tag}    │")
    print(f"  └──────┴──────────────────────────────────────────┴──────────┘")
    
    if overrejections:
        print(f"\n  ⚠️  TRUE OVER-REJECTIONS:")
        for r in overrejections:
            loc = r["answer"].find("未直接") 
            if loc < 0: loc = r["answer"].find("未涉及")
            if loc < 0: loc = r["answer"].find("未规定")
            ctx = r["answer"][max(0,loc-20):loc+60]
            print(f"    {r['name']}: ...{ctx}...")
    
    if hallucinations:
        print(f"\n  ⚠️  HALLUCINATIONS:")
        for r in hallucinations:
            print(f"    {r['name']}")

if __name__ == "__main__":
    sys.exit(main())
