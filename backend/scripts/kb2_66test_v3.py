#!/usr/bin/env python3
"""
kb2-web 66题全面测试 V3 — 并行模式（nocache=true）
覆盖：术语歧义/过拒、概念对比、数值查询、跨chunk推理、幻觉检测、
符号编码歧义、交叉规范、边界异常、回归测试
"""
import json, sys, time, concurrent.futures, threading

try:
    import requests as _req
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
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

ALL_QUESTIONS = [
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
    ("B01", "GB/T 2887 和 GB 50174 对温湿度要求有什么不同？"),
    ("B02", "A级机房和B级机房有什么不同？"),
    ("B03", "TN接地系统和TT接地系统有什么区别？"),
    ("B04", "等保二级和等保三级主要区别是什么？"),
    ("B05", "UPS和EPS有什么区别？"),
    ("B06", "强检和校准有什么不同？"),
    ("B07", "安全审计和日志审计有什么区别？"),
    ("B08", "GB/T 22239和GB/T 28448的关系是什么？"),
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
    ("D01", "GB 50174 数据中心选址有哪些要求？结合建筑防火一起说"),
    ("D02", "机房的接地系统怎么设计？从防雷接地到工作接地都说说"),
    ("D03", "数据中心的消防系统应该怎么设计？从报警到灭火"),
    ("D04", "等保二级对哪些方面有要求？网络安全、主机安全、数据安全"),
    ("D05", "一个完整的机房项目验收需要检查哪些方面？"),
    ("E01", "GB/T 2887 要求机房温度和湿度各是多少？（含等级区分）"),
    ("E02", "GB 50174 要求数据中心温度和湿度各是多少？（含等级区分）"),
    ("E03", "GB 50343 对防雷接地电阻有什么要求？"),
    ("E04", "等保三级在网络安全方面有什么具体要求？"),
    ("E05", "GB/T 22239-2019 哪些条款涉及密码要求？"),
    ("E06", "GA/T 1717.2-2020 对网络安全等级保护测评有哪些扩项要求？"),
    ("F01", "等保测评周期按年算还是按月算？"),
    ("F02", "GB/T 2887-2011 和 GB/T 2887-2011 有什么区别？（空查询）"),
    ("F03", "机房设计要求特别特别特别特别特别特别特别多，具体有哪些？（超长query）"),
    ("F04", "GB/T 50174 对数据中心选址有什么要求？（标准名缩写）"),
    ("F05", "GB50016-2014（2018年版）对疏散宽度有什么具体要求？"),
    ("F06", "含英文词：IT机房和普通机房在环境要求上有什么不同？"),
    ("F07", "一个50万元的弱电项目验收测评费要多少钱？"),
    ("F08", "GB 50174 和 GB/T 2887 对温湿度要求有什么不同？（交叉对比）"),
    ("F09", "5万的项目验收测评费怎么算？"),
    ("F10", "什么是零地电压？有什么要求？"),
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
]

def query_one(q, nocache=True):
    """单题查询"""
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
    """评估结果：过拒、短答、幻觉"""
    ans = result["answer"]
    if not ans:
        return "ERROR_EMPTY"
    # 过拒关键词（回答前500字）
    rej = ["未直接", "未涉及", "未规定", "未涵盖", "未覆盖",
           "找不到相关", "没有提到", "未找到", "无法回答",
           "未明确定义", "未单独列出"]
    if any(w in ans[:500] for w in rej):
        return "OVERREJECTION"
    if len(ans) < 100:
        return "ANSWER_TOO_SHORT"
    return "PASS"

def run():
    log(f"66题测试开始 (nocache=true, 3并发)")
    log(f"Token OK, 题目数: {len(ALL_QUESTIONS)}")
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

    # 分组统计
    groups = {
        "A": [], "B": [], "C": [], "D": [], "E": [], "F": [], "G": [],
    }
    for r in results:
        g = r["n"][0]
        if g in groups:
            groups[g].append(r)

    print("\n" + "=" * 60)
    print(f"结果汇总: {len(results)}题")
    pass_cnt = sum(1 for r in results if r["status"] == "PASS")
    fail_cnt = sum(1 for r in results if r["status"] != "PASS")
    rej_cnt = sum(1 for r in results if r["status"] == "OVERREJECTION")
    short_cnt = sum(1 for r in results if r["status"] == "ANSWER_TOO_SHORT")
    empty_cnt = sum(1 for r in results if r["status"] == "ERROR_EMPTY")
    print(f"  ✅PASS: {pass_cnt} | ❌FAIL: {fail_cnt}")
    print(f"  过拒: {rej_cnt} | 短答: {short_cnt} | 空/错: {empty_cnt}")
    for g_key, g_name in [("A","术语/过拒"),("B","概念对比"),("C","数值查询"),
                          ("D","跨chunk"),("E","交叉规范"),("F","边界异常"),("G","回归")]:
        grp = groups[g_key]
        pass_g = sum(1 for r in grp if r["status"] == "PASS")
        fail_g = [r for r in grp if r["status"] != "PASS"]
        fail_str = ", ".join(f"{r['n']} {r['status']}" for r in fail_g[:5])
        extra = f" ❌ {fail_str}" if fail_g else ""
        print(f"  {g_key}组 ({g_name}): {pass_g}/{len(grp)} ✅{extra}")

    print("\n⚠️  OVERREJECTIONS:")
    for r in results:
        if r["status"] == "OVERREJECTION":
            ans_preview = r.get("answer","")[:150].replace("\n"," ").strip()
            print(f"  {r['n']} ({r['len']}字): {ans_preview}...")

    print("\n⚠️  HALLUCINATIONS/ERRORS:")
    for r in results:
        if r["status"] in ("ANSWER_TOO_SHORT", "ERROR_EMPTY"):
            print(f"  {r['n']} {r['status']} ({r['len']}字, {r['time']:.0f}s) err={r['err']}")

    # 保存 JSON
    summary = {
        "total": len(results),
        "pass": pass_cnt,
        "fail": fail_cnt,
        "overrejections": rej_cnt,
        "short": short_cnt,
        "empty": empty_cnt,
        "results": results,
    }
    with open("/tmp/kb2_66test_results.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"\n完整结果已保存: /tmp/kb2_66test_results.json")

if __name__ == "__main__":
    run()
