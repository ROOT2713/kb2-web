#!/usr/bin/env python3
"""
kb2-web 84题全面测试 V5 — Wave 1+2 覆盖增强

新增内容：
1. S系列: B02拒答/位置拒答/会话白名单/缓存审计等Wave1+2修复回归
2. H系列: 政务信息化/造价/验收测评等领域题
3. Z系列: 安全\边界\复合场景
4. 拒答检测: NEEDS_REJECT 表 — 明确要求拒答的问题
"""
import json, sys, time, concurrent.futures, threading, os

try:
    import requests as _req
except ImportError:
    import subprocess, sys as _sys
    _sys.stdout.flush()
    subprocess.check_call([_sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests as _req

BASE = "http://127.0.0.1:3027"
USER, PASS = "admin", "adminljj0806!"

log_lock = threading.Lock()
def log(msg):
    with log_lock:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

def get_token():
    r = _req.post(f"{BASE}/api/auth/login", json={"username": USER, "password": PASS}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

TOKEN = get_token()

# ── LLM config ──
LLM_URL = None
LLM_KEY = None
LLM_MODEL = None
try:
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("LLM_BASE_URL="):
                LLM_URL = line.split("=", 1)[1].rstrip('"').lstrip('"')
            elif line.startswith("LLM_API_KEY="):
                LLM_KEY = line.split("=", 1)[1].rstrip('"').lstrip('"')
            elif line.startswith("LLM_MODEL="):
                LLM_MODEL = line.split("=", 1)[1].rstrip('"').lstrip('"')
    if LLM_URL and not LLM_URL.endswith("/chat/completions"):
        LLM_URL = LLM_URL.rstrip("/") + "/chat/completions"
except Exception:
    pass

# ── Rule-based expected answers ──
RULE_PASS = {
    # C series (保留): numeric standard values
    "C01": ["接地电阻", "1"],
    "C02": ["2.5", "净高"],
    "C03": ["防雷接地", "1"],
    "C04": ["测试", "频率"],
    "C05": ["屏蔽", "dB"],
    "C06": ["浮充", "电压"],
    "C07": ["电压", "允许波动"],
    "C08": ["弱电间", "弱电井", "尺寸"],
    "C09": ["湿度", "%"],
    "C10": ["等保", "测评", "一年", "1年"],
    "C11": ["密码", "测评", "一年", "1年"],
    "C12": ["防静电地板", "接地电阻", "1"],
    # F: fee
    "F07": ["50万", "验收", "测评"],
    "F09": ["5万", "验收测评", "费"],
    # G: fee + numeric
    "G10": ["等保三级", "测评费用"],
    "G11": ["弱电", "验收测评", "费"],
    "G12": ["电子会议", "接地电阻"],
    # E: cross-standard
    "E01": ["温度", "湿度", "2887"],
    "E02": ["温度", "湿度", "50174"],
    "E03": ["50343", "防雷", "接地电阻"],
    "E04": ["等保三级", "网络"],
    "E05": ["22239", "密码"],
    "E06": ["1717.2", "测评"],
    # A: terms
    "A09": ["2887", "温度"],
    "A13": ["2887", "湿度"],
    # H series: gov procurement
    "H01": ["广州", "政务信息化", "管理办法"],
    "H02": ["验收测评", "费用", "取费"],
    "H03": ["软件造价", "功能点"],
    "H04": ["36964", "功能点"],
    "H06": ["南沙", "信息化", "管理"],
    "H07": ["东莞", "造价", "指南"],
    "H08": ["电子政务", "建设", "费用"],
    "H09": ["密码应用", "方案", "评估"],
    "H10": ["密评", "安全", "评估"],
    # Z series: security
    "Z01": ["等保", "22239", "要求"],
    "Z02": ["等保", "28448", "测评"],
}

# ── Questions that MUST be rejected (substance or location rejection) ──
# Format: q_id -> list of keywords that indicate rejection
NEEDS_REJECT = {
    "S01": ["GB 50058", "未找到", "没有收录", "未包含", "未能找到", "无法回答", "未涉及"],
    "S02": ["北京", "未找到", "没有收录", "未包含", "未能找到"],
    "S03": ["GDPR", "未找到", "没有收录", "未包含", "未能找到"],
    "S04": ["深圳", "未找到", "没有收录", "未包含", "未能找到"],
    "S05": ["浙江", "未找到", "没有收录", "未包含", "未能找到"],
}

def rule_check(q_id: str, answer: str) -> str | None:
    """Rule match. Returns PASS/REJECT/None (needs LLM)."""
    ans_lower = answer.lower()
    # 1. Check NEEDS_REJECT first
    if q_id in NEEDS_REJECT:
        rej_terms = NEEDS_REJECT[q_id][1:]  # skip first (query term)
        if any(t in ans_lower for t in rej_terms):
            return "PASS"  # Correctly rejected
        # Check if answered with content (too long = not rejected)
        if len(answer) > 200:
            return "RULE_FAIL: should have rejected but gave content"
        return None  # Let LLM decide
    
    # 2. Normal RULE_PASS
    if q_id not in RULE_PASS:
        return None
    missing = []
    for kw in RULE_PASS[q_id]:
        if kw not in answer:
            missing.append(kw)
    if missing:
        return f"RULE_FAIL: missing {', '.join(missing)}"
    return "PASS"

# ── LLM judge ──
LLM_JUDGE_SYSTEM = """你是一个严格的问答质量评估员。评估标准：
1. 回答不能拒绝回答问题（不能说"未涉及""未提供"等）
2. 回答必须直接回应问题，不能答非所问
3. 回答必须有实质内容和具体信息
4. 回答必须有依据，不能凭空编造

输出格式：第一行 MUST BE exactly "PASS" 或 "FAIL"
第二行：简要理由（50字以内，中文）"""

def llm_judge(question: str, answer: str, max_retries: int = 3) -> tuple[str, str]:
    if not LLM_URL or not LLM_KEY:
        return "UNCERTAIN", "LLM not configured"
    prompt = f"## 问题\n{question}\n\n## 系统回答\n{answer[:3000]}"
    for attempt in range(max_retries):
        try:
            resp = _req.post(
                LLM_URL,
                headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
                json={
                    "model": LLM_MODEL or "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": LLM_JUDGE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 100,
                },
                timeout=30,
            )
            if resp.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            status = "PASS" if text.strip().startswith("PASS") else "FAIL"
            reason = text.strip().split("\n", 1)[1].strip() if "\n" in text else ""
            return status, reason
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                return "UNCERTAIN", str(e)[:60]
    return "UNCERTAIN", "max retries"

# ═══════════════════════════════════════════════════════════════════════
# Question bank — preserved V3 questions + new Wave 3 additions
# ═══════════════════════════════════════════════════════════════════════

ALL_QUESTIONS = [
    # ── A series: terms / overrejection (14) ──
    ("A01", "接线端子和接地端子有什么不同？"),
    ("A02", "备用电池能用多久？"),
    ("A03", "蜂鸣器一直响是什么问题？"),
    ("A04", "防雷接地和防静电接地是一回事吗？"),
    ("A05", "灭火器和气体灭火系统是一回事吗？"),
    ("A06", "保险丝和断路器有什么区别？"),
    ("A07", "UPS断电后能撑多久？"),
    ("A08", "接地和接零有什么区别？"),
    ("A09", "GB/T 2887 对机房温度有什么要求？"),
    ("A10", "综合布线的6类和超5类有什么不同？"),
    ("A11", "手机信号不好是不是因为机房电磁屏蔽？"),
    ("A12", "绿通是什么意思？"),
    ("A13", "GB/T 2887对机房相对湿度有什么要求？"),
    ("A14", "什么是零地电压？有什么要求？"),

    # ── B series: concept comparison (8) ──
    ("B01", "GB/T 2887 和 GB 50174 对温湿度要求有什么不同？"),
    ("B02", "A级机房和B级机房有什么不同？"),
    ("B03", "TN接地系统和TT接地系统有什么区别？"),
    ("B04", "等保二级和等保三级主要区别是什么？"),
    ("B05", "UPS和EPS有什么区别？"),
    ("B06", "强检和校准有什么不同？"),
    ("B07", "安全审计和日志审计有什么区别？"),
    ("B08", "GB/T 22239和GB/T 28448的关系是什么？"),

    # ── C series: numeric values (12) ──
    ("C01", "机柜的接地电阻是多少？"),
    ("C02", "GB 50174 要求的机房净高是多少？"),
    ("C03", "防雷接地的接地电阻要小于几欧？"),
    ("C04", "综合布线测试频率是多少？"),
    ("C05", "电磁屏蔽效能要求达到多少dB？"),
    ("C06", "UPS蓄电池的浮充电压是多少？"),
    ("C07", "供配电系统的电压允许波动范围是多少？"),
    ("C08", "弱电间/弱电井的尺寸要求是多少？"),
    ("C09", "机房的相对湿度标准是多少？"),
    ("C10", "等保测评要求多久做一次？"),
    ("C11", "密码测评要求多久做一次？"),
    ("C12", "防静电地板的接地电阻要求是多少？"),

    # ── D series: cross-chunk / comprehensive (5) ──
    ("D01", "GB 50174 数据中心选址有哪些要求？结合建筑防火一起说"),
    ("D02", "机房的接地系统怎么设计？从防雷接地到工作接地都说说"),
    ("D03", "数据中心的消防系统应该怎么设计？从报警到灭火"),
    ("D04", "等保二级对哪些方面有要求？网络安全、主机安全、数据安全"),
    ("D05", "一个完整的机房项目验收需要检查哪些方面？"),

    # ── E series: cross-standard (6) ──
    ("E01", "GB/T 2887 要求机房温度和湿度各是多少？（含等级区分）"),
    ("E02", "GB 50174 要求数据中心温度和湿度各是多少？（含等级区分）"),
    ("E03", "GB 50343 对防雷接地电阻有什么要求？"),
    ("E04", "等保三级在网络安全方面有什么具体要求？"),
    ("E05", "GB/T 22239-2019 哪些条款涉及密码要求？"),
    ("E06", "GA/T 1717.2-2020 对网络安全等级保护测评有哪些扩项要求？"),

    # ── F series: edge cases (10) ──
    ("F01", "等保测评周期按年算还是按月算？"),
    ("F02", "GB/T 2887-2011 和 GB/T 2887-2011 有什么区别？（空查询）"),
    ("F03", "机房设计要求特别特别特别特别特别特别特别多，具体有哪些？（超长query）"),
    ("F04", "GB/T 50174 对数据中心选址有什么要求？（标准名缩写）"),
    ("F05", "GB50016-2014（2018年版）对疏散宽度有什么具体要求？"),
    ("F06", "含英文词：IT机房和普通机房在环境要求上有什么不同？"),
    ("F07", "一个50万元的弱电项目验收测评费要多少钱？"),
    ("F08", "GB 50174 和 GB/T 2887 对温湿度要求有什么不同？（交叉对比）"),
    ("F09", "5万的项目验收测评费怎么算？"),
    ("F10", "GxP环境对精密空调有哪些特殊要求？"),

    # ── G series: regression (12) ──
    ("G01", "消防系统接地和防雷接地能共用吗？怎么连接？"),
    ("G02", "数据中心选址要考虑消防因素吗？有哪些要求？"),
    ("G03", "弱电系统的防雷检测周期是多久？"),
    ("G04", "K8密评是什么意思？怎么做？"),
    ("G05", "机柜内配线架怎么安装？有没有标准？"),
    ("G06", "三级等保的IPS/IDS有什么配置要求？"),
    ("G07", "数据中心的UPS容量怎么计算？"),
    ("G08", "防静电地板验收时主要检查什么？"),
    ("G09", "机房接地与防雷接地的区别和联系是什么？"),
    ("G10", "等保三级测评费用大概多少？"),
    ("G11", "弱电项目验收测评费用怎么算？"),
    ("G12", "电子会议系统的接地电阻有何要求？"),

    # ── S series: substance & location rejection (Wave 1+2 回归) (5) ──
    ("S01", "GB 50058 爆炸危险环境电气设计规范的内容是什么？"),
    ("S02", "北京市政务信息化项目管理办法有哪些具体规定？"),
    ("S03", "GDPR（通用数据保护条例）对个人信息保护有什么要求？"),
    ("S04", "深圳市政务信息化项目管理办法的具体内容是什么？"),
    ("S05", "浙江省政务信息化项目管理实施细则有哪些规定？"),

    # ── H series: gov procurement / fee / 政务信息化 (10) ──
    ("H01", "广州市政务信息化项目管理办法有哪些关键条款？"),
    ("H02", "政务信息化项目验收测评费取费标准是什么？"),
    ("H03", "软件造价评估实施规程中，功能点方法有哪些主要原则？"),
    ("H04", "GB/T 36964-2018 软件工程 软件开发成本度量规范的主要内容是什么？"),
    ("H05", "等保测评收费标准是怎样的？"),
    ("H06", "广州南沙区财政投资信息化项目的管理流程是怎样的？"),
    ("H07", "东莞市政府投资信息化项目造价指南有哪些主要内容？"),
    ("H08", "电子政务工程建设费用由哪些部分构成？"),
    ("H09", "密码应用安全性评估方案怎么编制？"),
    ("H10", "商用密码应用安全性评估（密评）的主要评估内容有哪些？"),

    # ── Z series: security & boundary (5) ──
    ("Z01", "GB/T 22239-2019 网络安全等级保护基本要求的主要内容是什么？"),
    ("Z02", "GB/T 28448-2019 网络安全等级保护测评要求有哪些关键变化？"),
    ("Z03", "GB 50348-2018 安全防范工程技术标准的施行日期是哪一天？"),
    ("Z04", "510万信息化项目验收测评费大致是多少？"),
    ("Z05", "政务信息化项目中，密码应用方案和密评报告的关系是什么？"),
]

RULE_IDS = set(RULE_PASS.keys()) | set(NEEDS_REJECT.keys())

# ── Query & evaluate ──

def query_one(q, nocache=True):
    t0 = time.time()
    try:
        r = _req.post(f"{BASE}/api/query",
            headers={"Authorization": f"Bearer {TOKEN}"},
            data={"q": q, "nocache": "true" if nocache else "false"},
            timeout=180)
        data = r.json()
        ans = data.get("answer", "")
        src = data.get("sources", [])
        elapsed = time.time() - t0
        return {"answer": ans, "sources": src, "time": elapsed, "err": None}
    except Exception as e:
        return {"answer": "", "sources": [], "time": time.time()-t0, "err": str(e)}

def evaluate(n, q_full, result):
    ans = result["answer"]
    if not ans:
        return "ERROR_EMPTY"
    # Tier 1: Basic checks
    rej = ["未直接", "未涉及", "未规定", "未涵盖", "未覆盖",
           "找不到相关", "没有提到", "未找到", "无法回答",
           "未明确定义", "未单独列出"]
    if any(w in ans[:500] for w in rej):
        return "OVERREJECTION"
    if len(ans) < 100:
        return "ANSWER_TOO_SHORT"
    # Tier 2: Rule-based
    rule_result = rule_check(n, ans)
    if rule_result == "PASS":
        return "PASS"
    if rule_result is not None:
        return rule_result
    # Tier 3: LLM 3x majority
    results = []
    for i in range(3):
        status, _ = llm_judge(q_full, ans)
        results.append(status)
    pass_cnt = results.count("PASS")
    fail_cnt = results.count("FAIL")
    uncertain_cnt = results.count("UNCERTAIN")
    if uncertain_cnt >= 2:
        return "LLM_UNCERTAIN"
    return "PASS" if pass_cnt >= 2 else ("LLM_FAIL" if fail_cnt >= 2 else "LLM_UNCERTAIN")

# ── History tracking ──
RESULT_FILE = "/tmp/kb2_84test_results.json"
HISTORY_FILE = "/tmp/kb2_84test_history.json"

def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"runs": []}

def save_history(pass_count, total):
    history = load_history()
    run = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pass": pass_count, "total": total, "rate": round(pass_count / max(total, 1) * 100, 1)}
    history["runs"].append(run)
    history["runs"] = history["runs"][-20:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return history

def check_trend(history):
    runs = history.get("runs", [])
    if len(runs) < 4:
        return None
    recent = runs[-3:]
    prev = runs[-4]
    rates = [r["rate"] for r in recent]
    drops = all(rates[i] < rates[i-1] and (rates[i-1] - rates[i]) >= 1.0 for i in range(1, 3))
    if drops:
        return f"BLOCK: 通过率连续3次下降 ({rates[0]}% → {rates[1]}% → {rates[2]}%), 基线{prev['rate']}%"
    return None

# ── Main ──

GROUP_NAMES = {
    "A": "术语/过拒", "B": "概念对比", "C": "数值查询",
    "D": "跨chunk", "E": "交叉规范", "F": "边界异常",
    "G": "回归", "S": "拒答回归(W1+W2)", "H": "政务信息化",
    "Z": "安全/边界",
}

def run():
    log(f"84题全面测试 V5 开始 (nocache=true, 3并发)")
    log(f"Token OK, 题目数: {len(ALL_QUESTIONS)}")
    log(f"规则匹配: {len(RULE_PASS)}题 + 拒答检测: {len(NEEDS_REJECT)}题")
    if LLM_URL:
        log(f"LLM评估已配置: {LLM_MODEL or 'default'}")
    else:
        log("⚠️ LLM评估未配置 — 仅使用规则匹配")
    log("")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        fut_map = {}
        for n, q in ALL_QUESTIONS:
            f = ex.submit(query_one, q)
            fut_map[f] = (n, q)

        done_cnt = 0
        for f in concurrent.futures.as_completed(fut_map):
            n, q = fut_map[f]
            r = f.result()
            status = evaluate(n, q, r)
            results.append({"n": n, "q": q, "status": status, "len": len(r["answer"]), "time": r["time"], "err": r["err"]})
            done_cnt += 1
            log(f"[{done_cnt}/{len(ALL_QUESTIONS)}] {n}: {status} ({len(r['answer'])}字, {r['time']:.0f}s)")

    # Group stats
    groups = {}
    for r in results:
        g = r["n"][0]
        groups.setdefault(g, []).append(r)

    PASS_STATUSES = {"PASS"}
    pass_cnt = sum(1 for r in results if r["status"] in PASS_STATUSES)
    rule_fail = sum(1 for r in results if r["status"].startswith("RULE_FAIL"))
    llm_fail = sum(1 for r in results if r["status"] in ("LLM_FAIL", "LLM_UNCERTAIN"))
    rej_cnt = sum(1 for r in results if r["status"] == "OVERREJECTION")
    short_cnt = sum(1 for r in results if r["status"] == "ANSWER_TOO_SHORT")
    empty_cnt = sum(1 for r in results if r["status"] == "ERROR_EMPTY")

    print("\n" + "=" * 60)
    print(f"结果汇总: {len(results)}题")
    fail_cnt = len(results) - pass_cnt
    print(f"  ✅PASS: {pass_cnt} | ❌FAIL: {fail_cnt}")
    print(f"  规则失败: {rule_fail} | LLM拒答: {llm_fail} | 过拒: {rej_cnt} | 短答: {short_cnt} | 空/错: {empty_cnt}")
    for g_key in sorted(groups.keys()):
        grp = groups[g_key]
        g_name = GROUP_NAMES.get(g_key, g_key)
        pass_g = sum(1 for r in grp if r["status"] in PASS_STATUSES)
        fail_g = [r for r in grp if r["status"] not in PASS_STATUSES]
        fail_str = ", ".join(f"{r['n']} {r['status']}" for r in fail_g[:5])
        extra = f" ❌ {fail_str}" if fail_g else ""
        print(f"  {g_key}组 ({g_name}): {pass_g}/{len(grp)} ✅{extra}")

    print("\n⚠️ FAILURES:")
    for r in results:
        if r["status"] not in PASS_STATUSES:
            s = r.get("answer", "N/A")[:200].replace("\n", " ").strip()
            print(f"  {r['n']} ({r['status']}): {s}...")

    # Save
    summary = {
        "total": len(results),
        "pass": pass_cnt,
        "fail": fail_cnt,
        "rule_fail": rule_fail,
        "llm_fail": llm_fail,
        "overrejections": rej_cnt,
        "short": short_cnt,
        "empty": empty_cnt,
        "results": results,
    }
    with open(RESULT_FILE, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"\n完整结果已保存: {RESULT_FILE}")

    # Trend
    history = save_history(pass_cnt, len(results))
    trend_msg = check_trend(history)
    if trend_msg:
        print(f"\n🔴 TREND ALERT: {trend_msg}")
        log("🔴 趋势告警 — 连续3次下降，建议审查本次变更后再合并")
        return 1

    log(f"\n✅ 通过率: {pass_cnt}/{len(results)} ({round(pass_cnt/max(len(results),1)*100, 1)}%)")
    if fail_cnt > len(results) * 0.3:
        log("❌ 通过率低于70%，基线严重下降")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(run())
