#!/usr/bin/env python3
"""
kb2-web 66题全面测试 V3
覆盖：术语歧义/过拒、概念对比、数值查询、跨chunk推理、幻觉检测、
符号编码歧义、交叉规范、边界异常、回归测试
"""
import subprocess, json, sys, re, time

BASE = "http://127.0.0.1:3027"
TOKEN = None

def login():
    global TOKEN
    r = subprocess.run(
        ["/usr/bin/curl", "-s", "-X", "POST", f"{BASE}/api/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"username":"admin","password":"adminljj0806!"}'],
        capture_output=True, text=True, timeout=15
    )
    try:
        data = json.loads(r.stdout)
        TOKEN = data["access_token"]
        return True
    except:
        print(f"LOGIN_FAILED: {r.stdout[:200]}")
        return False

def query(q, nocache=True):
    curl_args = [
        "/usr/bin/curl", "-s", "-X", "POST", f"{BASE}/api/query",
        "-H", f"Authorization: Bearer {TOKEN}",
        "--data-urlencode", f"q={q}",
    ]
    if nocache:
        curl_args.extend(["--data-urlencode", "nocache=true"])
    r = subprocess.run(curl_args, capture_output=True, text=True, timeout=180)
    try:
        return json.loads(r.stdout)
    except:
        return {"error": f"PARSE_FAILED: {r.stdout[:300]}"}

def run_test(name, q, doc_hint="", expected_rejection_correct=False, min_chunks=1, expect_no_hallucination=True):
    """Run a single test and return structured result."""
    resp = query(q)
    ans = resp.get("answer", "")
    sources = [s.get("doc", "")[:60] for s in resp.get("sources", [])]
    has_doc = any(doc_hint in s for s in sources) if doc_hint else True

    issues = []

    # 1. Over-rejection check
    rejection_words = ["未直接", "未涉及", "未规定", "未涵盖", "未覆盖", "找不到相关"]
    in_rejection = any(w in ans[:500] for w in rejection_words)
    if has_doc and in_rejection and not expected_rejection_correct:
        issues.append("OVERREJECTION")

    # 2. Source check
    if not sources:
        issues.append("NO_SOURCES")
    elif doc_hint and not has_doc and not expected_rejection_correct:
        issues.append("MISSING_DOC")

    # 3. Hallucination check
    if expect_no_hallucination and re.search(r"建议[查阅看].*第[五六七八九十\d一二三四五六七八九十百]+章", ans[:600]):
        issues.append("HALLUCINATION_CHAPTER")

    # 4. Answer quality
    ans_len = len(ans)
    if ans_len < 30:
        issues.append(f"ANSWER_TOO_SHORT({ans_len}字)")
    elif ans_len < 100 and not expected_rejection_correct:
        issues.append(f"ANSWER_SUSPICIOUSLY_SHORT({ans_len}字)")

    status = "PASS" if not issues else "FAIL"
    ans_preview = ans[:120].replace('\n', ' ').strip()

    return {
        "name": name, "q": q, "status": status,
        "issues": issues, "ans_len": ans_len,
        "sources": sources[:3], "ans_preview": ans_preview,
        "has_doc": has_doc, "in_rejection": in_rejection,
        "answer": ans
    }

def print_result(r, idx):
    tag = "✅" if r["status"] == "PASS" else "❌"
    print(f"  [{tag}] ({idx:02d}) {r['name']:<42s} {r['ans_len']:>4d}字")
    if r["issues"]:
        print(f"         Issues: {', '.join(r['issues'])}")
    if r["sources"]:
        srcs = r["sources"][:2]
        print(f"         Sources: {' | '.join(s.rsplit('/',1)[-1][:25] for s in srcs)}")

def main():
    if not login():
        return 1

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  kb2-web 66题综合测试 V3                                ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = []

    # ═══════════════════════════════════════════════════
    # GROUP A: 术语歧义 / 过拒 (13题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ A组: 术语歧义 / 过拒 (13题) ═══════")

    A = [
        ("A01 接地端子→接线端子", "GB 16806-2006《消防联动控制系统》对接地端子有什么要求？", "16806", True),
        ("A02 备用电池→蓄电池", "GB 16806-2006 规定备用电池能用多久？", "16806", False),
        ("A03 蜂鸣器→音响报警", "GB 16806 里说消防设备蜂鸣器一直响是什么情况？", "16806", False),
        ("A04 防雷→浪涌保护接地", "GB 16806-2006 对防雷有什么要求？", "16806", True),
        ("A05 按钮按不下去（正确拒）", "消防联动控制器的按钮按不下去怎么办，GB 16806 有要求吗？", "16806", True),
        ("A06 220V断电→主备电源", "GB 16806 规定主电源断电后怎么办？", "16806", False),
        ("A07 铁皮柜→机柜", "GB 50174 对数据中心机柜接地有什么要求？", "50174", False),
        ("A08 插座→电源分配", "GB 50174 对数据中心PDU/插座有什么要求？", "50174", False),
        ("A09 空调温度→机房温湿度", "GB/T 2887 对机房温度有什么要求？", "2887", False),
        ("A10 网络不通→综合布线", "GB/T 50312 对综合布线测试有什么要求？", "50312", False),
        ("A11 手机信号→电磁屏蔽", "数据中心电磁屏蔽效能有什么要求？", "12190", False),
        ("A12 绿通→应急通道", "GB 50016 对消防疏散通道宽度有什么要求？", "50016", False),
        ("A13 漏水→温湿度控制（正确拒）", "GB 50174 对数据中心防漏水有什么具体规定？", "50174", True),
    ]
    for n, q, dh, erc in A:
        results.append(run_test(n, q, doc_hint=dh, expected_rejection_correct=erc))

    # ═══════════════════════════════════════════════════
    # GROUP B: 概念对比 (8题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ B组: 概念对比 (8题) ═══════")

    B = [
        ("B01 接线端子 vs 接地端子", "接线端子和接地端子有什么不同？", "16806"),
        ("B02 A级 vs B级机房", "GB 50174 中A级和B级机房有什么不同？", "50174"),
        ("B03 TN vs TT 接地系统", "TN系统与TT系统有什么区别？", "配电"),
        ("B04 等保二级 vs 三级", "网络安全等级保护二级和三级有什么不同？", "22239"),
        ("B05 防雷 vs 防静电", "建筑物防雷与防静电在设计上有什么不同？", "50057"),
        ("B06 强检 vs 校准", "测量设备强检和校准有什么区别？", "CNAS"),
        ("B07 验收测评 vs 监理", "验收测评和信息化监理有什么区别？", "验收"),
        ("B08 屏蔽室 vs 电波暗室", "电磁屏蔽室与电波暗室的设计要求有什么不同？", "12190"),
    ]
    for n, q, dh in B:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # GROUP C: 数值查询 (12题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ C组: 数值查询 (12题) ═══════")

    C = [
        ("C01 机柜接地电阻", "GB 50174 对机柜接地电阻值有什么要求？", "50174"),
        ("C02 机房温度范围", "GB/T 2887-2011 A级机房开机时温度范围是多少？", "2887"),
        ("C03 防雷接地电阻", "GB 50057 对接地电阻值有什么要求？", "50057"),
        ("C04 综合布线测试频率", "GB/T 50312 综合布线测试的频率范围是多少？", "50312"),
        ("C05 电磁屏蔽效能dB", "GB/T 12190 电磁屏蔽室的屏蔽效能应达到多少dB？", "12190"),
        ("C06 消防报警延迟", "GB 16806 要求传输设备故障报警在多少秒内？", "16806"),
        ("C07 供配电电压范围", "数据中心机房对供电电压偏差有什么要求？", "电压偏差"),
        ("C08 网络带宽要求", "GB/T 50311 对布线系统信道带宽有什么要求？", "50311"),
        ("C09 机房湿度范围", "GB/T 2887-2011 对机房相对湿度有什么要求？", "2887"),
        ("C10 等保测评周期", "等保测评要求多久做一次？", "等保"),
        ("C11 密码测评频率", "商用密码应用安全性评估多久一次？", "密码"),
        ("C12 防静电地板电阻", "防静电地板的系统电阻值要求是多少？", "防静电"),
    ]
    for n, q, dh in C:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # GROUP D: 跨chunk推理 (5题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ D组: 跨chunk推理 (5题) ═══════")

    D = [
        ("D01 电源系统总览", "GB 16806-2006 对电源系统有什么要求？", "16806"),
        ("D02 接地系统总结", "消防系统的接地要求有哪些规范涉及？", "接地"),
        ("D03 数据中心综合要求", "数据中心选址应考虑哪些因素？", "50174"),
        ("D04 验收评测依据", "政务信息化项目的验收测评应依据哪些标准？", "验收"),
        ("D05 防雷总体架构", "建筑物需做哪些防雷措施？", "50057"),
    ]
    for n, q, dh in D:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # GROUP E: 幻觉检测 (7题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ E组: 幻觉检测 (7题) ═══════")

    E = [
        ("E01 字数元数据", "GB 16806-2006 全文共有多少字？有几章？", "16806"),
        ("E02 不存在的章节", "GB 16806-2006 第15章讲了什么？", "16806", True),
        ("E03 规范发布日期", "GB 50174-2017 是什么时候发布的？", "50174"),
        ("E04 不存在标准（正确拒）", "GB/T 88888-2025 对软件测试有什么要求？", None, True),
        ("E05 不存在的规范（正确拒）", '请解释"GB 99999-2099 数据中心设计规范"的内容', None, True),
        ("E06 KB中无此文档（正确拒）", "工信部 信部〔2020〕666号 讲了什么？", None, True),
        ("E07 GB 16806 标准号来源", "GB 16806-2006 这个标准号代表什么意思？", "16806"),
    ]
    for item in E:
        if len(item) == 4:
            n, q, dh, erc = item
        else:
            n, q, dh = item
            erc = False
        results.append(run_test(n, q, doc_hint=dh or "", expected_rejection_correct=erc))

    # ═══════════════════════════════════════════════════
    # GROUP F: 符号/编码歧义 (5题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ F组: 符号/编码歧义 (5题) ═══════")

    F = [
        ("F01 GB/T vs GB 混淆", "GB/T 25000.51 与 GB 25000.51 是同一个标准吗？", "25000.51"),
        ("F02 标准号斜杠写法", "GB/T 2887-2011 对机房洁净度有什么要求？", "2887"),
        ("F03 GB-T 全角写法", "GB—T 50314-2015 对智能化有什么要求？", "50314"),
        ("F04 标准名缩写", "GB50174里对数据中心选址有啥要求？", "50174"),
        ("F05 中英文混写", "GB/T 25000.51 System and software engineering 对测试有什么要求？", "25000.51"),
    ]
    for n, q, dh in F:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # GROUP G: 交叉规范 (5题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ G组: 交叉规范 (5题) ═══════")

    G = [
        ("G01 消防+接地交叉", "消防系统和防雷接地系统之间的关系？", "16806"),
        ("G02 数据中心+消防交叉", "数据中心的消防系统应满足什么标准？", "50016"),
        ("G03 等保+密码交叉", "等保三级系统是否需要进行商用密码应用安全性评估？", "22239"),
        ("G04 验收+造价交叉", "验收测评的费用如何根据项目规模确定？", "第三部分"),
        ("G05 布线+屏蔽交叉", "综合布线系统对电磁屏蔽有什么要求？", "50312"),
    ]
    for n, q, dh in G:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # GROUP H: 边界/异常 (5题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ H组: 边界/异常 (5题) ═══════")

    H = [
        ("H01 极小金额", "D=5万元的软件项目验收评测费怎么算？", "第三部分"),
        ("H02 极大金额", "D=10亿元的信息化项目怎么算设计费？", "东莞"),
        ("H03 模糊查询", "机房标准", "50174"),
        ("H04 多意图查询", "等保三级多少钱？机房温度要求多少？", "第三部分"),
        ("H05 超长query(50字)", "请帮我查一下广东省政务信息化项目管理办法中关于验收、监理、设计、造价、密码等方面有哪些具体要求？", "粤府办"),
    ]
    for n, q, dh in H:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # GROUP I: 回归测试 (6题)
    # ═══════════════════════════════════════════════════
    print("\n═══════ I组: 回归测试 (6题) ═══════")

    I = [
        ("I01(K1) 验收评测费510万", "电子政务软件系统建设规模D=510万元，请问验收评测费是多少？", "第三部分"),
        ("I02(K4) 等保三级费用", "电子政务三级等保测评费用是多少？", "第三部分"),
        ("I03(K8) 验收评测费generic", "D=510万元的软件项目，验收评测费怎么算？", "第三部分"),
        ("I04(K9) 通用非计费", "GB/T 25000.51-2016 对验收测试流程有什么要求？", "25000.51"),
        ("I05(K10) 东莞设计费", "东莞政府投资的6000万元信息化项目，设计费如何计算？", "东莞"),
        ("I06(K11) 非费用不污染", "GB/T 2887-2011《计算机场地通用规范》对机房温度有什么要求？", "2887"),
    ]
    for n, q, dh in I:
        results.append(run_test(n, q, doc_hint=dh))

    # ═══════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    overrejections = [r for r in results if "OVERREJECTION" in str(r["issues"])]
    hallucinations = [r for r in results if "HALLUCINATION_CHAPTER" in str(r["issues"])]
    short_answers = [r for r in results if "ANSWER_TOO_SHORT" in str(r["issues"]) or "ANSWER_SUSPICIOUSLY_SHORT" in str(r["issues"])]

    print(f"\n{'='*60}")
    print(f"结果汇总: {len(results)}题 | ✅PASS: {passed} | ❌FAIL: {failed}")
    print(f"  过拒: {len(overrejections)} | 幻觉: {len(hallucinations)} | 短答: {len(short_answers)}")

    # Per-group summary
    groups = {"A": A, "B": B, "C": C, "D": D, "E": E, "F": F, "G": G, "H": H, "I": I}
    offset = 0
    for gname, gdata in groups.items():
        n_tests = len(gdata)
        g_results = results[offset:offset+n_tests]
        g_pass = sum(1 for r in g_results if r["status"] == "PASS")
        g_fail = sum(1 for r in g_results if r["status"] == "FAIL")
        print(f"  {gname}组: {g_pass}/{n_tests} ✅", end="")
        if g_fail:
            fails = [r["name"] for r in g_results if r["status"] == "FAIL"]
            print(f"  ❌ {', '.join(fails)}", end="")
        print()
        offset += n_tests

    if overrejections:
        print(f"\n⚠️  TRUE OVER-REJECTIONS:")
        for r in overrejections:
            print(f"    {r['name']}: {r['ans_preview'][:100]}...")

    if hallucinations:
        print(f"\n⚠️  HALLUCINATIONS:")
        for r in hallucinations:
            print(f"    {r['name']}")

    # Save full results JSON for CC review
    with open("/tmp/kb2_60test_results.json", "w") as f:
        clean = []
        for r in results:
            clean.append({k: r[k] for k in ["name","q","status","issues","ans_len","sources","has_doc","in_rejection","ans_preview"]})
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果已保存: /tmp/kb2_60test_results.json")

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
