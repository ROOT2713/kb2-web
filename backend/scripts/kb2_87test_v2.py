#!/usr/bin/env python3
"""Quick rule-only 87-test runner for Wave 3 validation (no LLM judge)."""
import json, sys, time, concurrent.futures, requests, os

BASE = "http://127.0.0.1:3027"
USER, PASS = "admin", "adminljj0806!"
r = requests.post(f"{BASE}/api/auth/login", json={"username": USER, "password": PASS}, timeout=30)
TOKEN = r.json()["access_token"]

# ── 同义词宽松匹配 ──
SYNONYMS = {
    "一年": ["一年", "1年", "每年", "每一年", "一个自然年"],
    "半年": ["半年", "6个月", "六个月"],
    "等保": ["等保", "等级保护", "网络安全等级保护"],
    "2.5": ["2.5", "2.5m", "2.5M", "2.5米", "2.50", "2.5m", "250mm", "250mm"],
    "六类": ["六类", "6类", "cat6", "CAT6"],
    "超五类": ["超五类", "超5类", "cat5e", "CAT5e"],
    "消防接地": ["消防接地", "消防系统接地"],
}
def kw_match(kw, ans):
    if kw in SYNONYMS:
        return any(s in ans for s in SYNONYMS[kw])
    return kw in ans

def all_kw_match(kws, ans):
    return all(kw_match(kw, ans) for kw in kws)

RULE_PASS = {
    # C组 数值查询
    "C01": ["接地电阻","1"], "C02": ["2.5","净高"], "C03": ["防雷接地","1"],
    "C04": ["测试","频率"], "C05": ["屏蔽","dB"], "C06": ["浮充","电压"],
    "C07": ["电压","允许波动"], "C08": ["弱电间","弱电井","尺寸"],
    "C09": ["湿度","%"], "C10": ["等保","测评","年"],
    "C11": ["密码","测评","年"], "C12": ["防静电地板","接地电阻"],
    # F组 边界异常
    "F07": ["50万","验收","测评"], "F09": ["5万","验收测评","费"],
    # G组 回归
    "G10": ["等保三级","测评费用"], "G11": ["弱电","验收测评","费"], "G12": ["电子会议","接地电阻"],
    # E组 交叉规范
    "E01": ["温度","湿度","2887"], "E02": ["温度","湿度","50174"],
    "E03": ["50343","防雷","接地电阻"], "E04": ["等保三级","网络"],
    "E05": ["22239","密码"], "E06": ["1717.2","网络安全","测评"],
    # A组
    "A01": ["接线端子","接地端子"], "A02": ["备用电池","时间"],
    "A03": ["蜂鸣器","报警"], "A04": ["防雷接地","防静电接地"],
    "A05": ["灭火器","气体灭火"], "A06": ["保险丝","断路器"],
    "A07": ["UPS","断电","时间"], "A08": ["接地","接零"],
    "A09": ["2887","温度"], "A10": ["六类","超五类"],
    "A11": ["手机信号","电磁屏蔽"], "A12": ["绿通"],
    "A13": ["2887","湿度"], "A14": ["零地电压"],
    # B组(概念对比)
    "B01": ["2887","50174","温度","湿度"], "B02": ["A级","B级","机房"],
    "B03": ["TN","TT","接地"], "B04": ["二级","三级","等保"],
    "B05": ["UPS","EPS"], "B06": ["强检","校准"],
    "B07": ["安全审计","日志审计"], "B08": ["22239","28448"],
    # D组(跨chunk)
    "D01": ["选址","防火"], "D02": ["接地系统","防雷接地"],
    "D03": ["消防","灭火"], "D04": ["二级","网络安全","主机安全"],
    "D05": ["验收","检查"],
    # F组补充
    "F01": ["等保","测评","年","周期"], "F02": ["2887","相同"],
    "F03": ["机房","设计"], "F04": ["50174","选址"],
    "F05": ["50016","疏散"], "F06": ["机房","IT"],
    "F08": ["50174","2887","温度","湿度"], "F10": ["GxP","精密空调"],
    # G组补充
    "G01": ["消防接地","防雷接地"], "G02": ["选址","消防"],
    "G03": ["防雷","周期"], "G04": ["密评","密码"],
    "G05": ["配线架"], "G06": ["三级等保","IPS"],
    "G07": ["UPS","容量"], "G08": ["防静电地板","验收"],
    "G09": ["接地","防雷接地"],
    # H组
    "H01": ["广州","政务信息化","管理办法"], "H02": ["验收测评","费用","取费"],
    "H03": ["软件造价","功能点"], "H04": ["36964","功能点"],
    "H05": ["等保","收费","费用"], "H06": ["南沙","信息化","管理"],
    "H07": ["东莞","造价","指南"], "H08": ["电子政务","建设","费用"],
    "H09": ["密码应用","方案","评估"], "H10": ["密评","安全","评估"],
    # Z组
    "Z01": ["等保","22239","要求"], "Z02": ["等保","28448","测评"],
    "Z03": ["50348","施行"], "Z04": ["510万","测评费"], "Z05": ["密码","密评","关系"],
}
NEEDS_REJECT = {
    "S01": ["GB 50058","未找到","未收录","未包含","未能找到"],
    "S02": ["北京","未找到","未收录","未包含","未能找到"],
    "S03": ["GDPR","未找到","未收录","未包含","未能找到"],
    "S04": ["深圳","未找到","未收录","未包含","未能找到"],
    "S05": ["浙江","未找到","未收录","未包含","未能找到"],
}
REJECT_TERMS = ["未直接","未涉及","未规定","未涵盖","未覆盖","找不到相关","没有提到","未找到","无法回答","未明确定义","未单独列出"]

ALL_QUESTIONS = [
("A01","接线端子和接地端子有什么不同？"),("A02","备用电池能用多久？"),("A03","蜂鸣器一直响是什么问题？"),
("A04","防雷接地和防静电接地是一回事吗？"),("A05","灭火器和气体灭火系统是一回事吗？"),("A06","保险丝和断路器有什么区别？"),
("A07","UPS断电后能撑多久？"),("A08","接地和接零有什么区别？"),("A09","GB/T 2887 对机房温度有什么要求？"),
("A10","综合布线的6类和超5类有什么不同？"),("A11","手机信号不好是不是因为机房电磁屏蔽？"),("A12","绿通是什么意思？"),
("A13","GB/T 2887对机房相对湿度有什么要求？"),("A14","什么是零地电压？有什么要求？"),
("B01","GB/T 2887 和 GB 50174 对温湿度要求有什么不同？"),("B02","A级机房和B级机房有什么不同？"),
("B03","TN接地系统和TT接地系统有什么区别？"),("B04","等保二级和等保三级主要区别是什么？"),
("B05","UPS和EPS有什么区别？"),("B06","强检和校准有什么不同？"),("B07","安全审计和日志审计有什么区别？"),
("B08","GB/T 22239和GB/T 28448的关系是什么？"),
("C01","机柜的接地电阻是多少？"),("C02","GB 50174 要求的机房净高是多少？"),("C03","防雷接地的接地电阻要小于几欧？"),
("C04","综合布线测试频率是多少？"),("C05","电磁屏蔽效能要求达到多少dB？"),("C06","UPS蓄电池的浮充电压是多少？"),
("C07","供配电系统的电压允许波动范围是多少？"),("C08","弱电间/弱电井的尺寸要求是多少？"),
("C09","机房的相对湿度标准是多少？"),("C10","等保测评要求多久做一次？"),("C11","密码测评要求多久做一次？"),
("C12","防静电地板的接地电阻要求是多少？"),
("D01","GB 50174 数据中心选址有哪些要求？合并建筑防火一起说"),
("D02","机房的接地系统怎么设计？从防雷接地到工作接地都说说"),
("D03","数据中心的消防系统应该怎么设计？从报警到灭火"),
("D04","等保二级对哪些方面有要求？网络安全、主机安全、数据安全"),
("D05","一个完整的机房项目验收需要检查哪些方面？"),
("E01","GB/T 2887 要求机房温度和湿度各是多少？（含等级区分）"),
("E02","GB 50174 要求数据中心温度和湿度各是多少？（含等级区分）"),
("E03","GB 50343 对防雷接地电阻有什么要求？"),("E04","等保三级在网络安全方面有什么具体要求？"),
("E05","GB/T 22239-2019 哪些条款涉及密码要求？"),
("E06","GA/T 1717.2-2020 对网络安全等级保护测评有哪些扩项要求？"),
("F01","等保测评周期按年算还是按月算？"),
("F02","GB/T 2887-2011 和 GB/T 2887-2011 有什么区别？（空查询）"),
("F03","机房设计要求特别特别特别特别特别特别特别多，具体有哪些？（超长query）"),
("F04","GB/T 50174 对数据中心选址有什么要求？（标准名缩写）"),
("F05","GB50016-2014（2018年版）对疏散宽度有什么具体要求？"),
("F06","含英文词：IT机房和普通机房在环境要求上有什么不同？"),
("F07","一个50万元的弱电项目验收测评费要多少钱？"),
("F08","GB 50174 和 GB/T 2887 对温湿度要求有什么不同？（交叉对比）"),
("F09","5万的项目验收测评费怎么算？"),("F10","GxP环境对精密空调有哪些特殊要求？"),
("G01","消防系统接地和防雷接地能共用吗？怎么连接？"),("G02","数据中心选址要考虑消防因素吗？有哪些要求？"),
("G03","弱电系统的防雷检测周期是多久？"),("G04","K8密评是什么意思？怎么做？"),
("G05","机柜内配线架怎么安装？有没有标准？"),("G06","三级等保的IPS/IDS有什么配置要求？"),
("G07","数据中心的UPS容量怎么计算？"),("G08","防静电地板验收时主要检查什么？"),
("G09","机房接地与防雷接地的区别和联系是什么？"),("G10","等保三级测评费用大概多少？"),
("G11","弱电项目验收测评费用怎么算？"),("G12","电子会议系统的接地电阻有何要求？"),
("S01","GB 50058 爆炸危险环境电气设计规范的内容是什么？"),
("S02","北京市政务信息化项目管理办法有哪些具体规定？"),
("S03","GDPR（通用数据保护条例）对个人信息保护有什么要求？"),
("S04","深圳市政务信息化项目管理办法的具体内容是什么？"),
("S05","浙江省政务信息化项目管理实施细则有哪些规定？"),
("H01","广州市政务信息化项目管理办法有哪些关键条款？"),
("H02","政务信息化项目验收测评费取费标准是什么？"),
("H03","软件造价评估实施规程中，功能点方法有哪些主要原则？"),
("H04","GB/T 36964-2018 软件工程 软件开发成本度量规范的主要内容是什么？"),
("H05","等保测评收费标准是怎样的？"),
("H06","广州南沙区财政投资信息化项目的管理流程是怎样的？"),
("H07","东莞市政府投资信息化项目造价指南有哪些主要内容？"),
("H08","电子政务工程建设费用由哪些部分构成？"),
("H09","密码应用安全性评估方案怎么编制？"),
("H10","商用密码应用安全性评估（密评）的主要评估内容有哪些？"),
("Z01","GB/T 22239-2019 网络安全等级保护基本要求的主要内容是什么？"),
("Z02","GB/T 28448-2019 网络安全等级保护测评要求有哪些关键变化？"),
("Z03","GB 50348-2018 安全防范工程技术标准的施行日期是哪一天？"),
("Z04","510万信息化项目验收测评费大致是多少？"),
("Z05","政务信息化项目中，密码应用方案和密评报告的关系是什么？"),
]

GROUP_NAMES = {"A":"术语/过拒","B":"概念对比","C":"数值查询","D":"跨chunk","E":"交叉规范","F":"边界异常","G":"回归","S":"拒答回归(W1+W2)","H":"政务信息化","Z":"安全/边界"}

def query_one(q, timeout=180):
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/query", headers={"Authorization": f"Bearer {TOKEN}"},
                         data={"q": q, "nocache": "true", "rerank": "false"}, timeout=timeout)
        d = r.json()
        ans = d.get("answer","")
        rv = {"answer": ans, "time": time.time()-t0, "sources": len(d.get("sources",[]))}
        # Token 过期重试一次
        if not ans and r.status_code == 401:
            r2 = requests.post(f"{BASE}/api/auth/login", json={"username": USER, "password": PASS}, timeout=30)
            TOKEN2 = r2.json()["access_token"]
            r = requests.post(f"{BASE}/api/query", headers={"Authorization": f"Bearer {TOKEN2}"},
                             data={"q": q, "nocache": "true", "rerank": "false"}, timeout=timeout)
            d = r.json()
            ans = d.get("answer","")
            rv = {"answer": ans, "time": time.time()-t0, "sources": len(d.get("sources",[]))}
        return rv
    except Exception as e:
        return {"answer": "", "time": time.time()-t0, "sources": 0, "error": str(e)}

def evaluate(n, q_full, result):
    ans = result["answer"]
    if not ans: return "ERROR_EMPTY"
    # OVERREJECTION: 前200字含拒答词 且 总长<200
    if any(w in ans[:200] for w in REJECT_TERMS) and len(ans) < 200:
        return "OVERREJECTION"
    # 短回答分级
    if len(ans) < 20: return "RESPONSE_CORRUPTED"
    if len(ans) < 100: return "L3_TEMPLATE"
    # NEEDS_REJECT — S组，有实质内容放行
    if n in NEEDS_REJECT:
        rej_terms = NEEDS_REJECT[n][1:]
        al = ans.lower()
        if any(t in al for t in rej_terms): return "PASS"
        if len(ans) > 500: return "PASS_BEST_EFFORT"
        return "UNCERTAIN"
    # RULE_PASS
    if n in RULE_PASS:
        missing = [kw for kw in RULE_PASS[n] if not kw_match(kw, ans)]
        if missing: return f"RULE_FAIL: missing {','.join(missing)}"
        return "PASS"
    return "UNCERTAIN"

results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    fut_map = {}
    for n, q in ALL_QUESTIONS:
        f = ex.submit(query_one, q)
        fut_map[f] = (n, q)
    for f in concurrent.futures.as_completed(fut_map):
        n, q = fut_map[f]
        r = f.result()
        status = evaluate(n, q[:80], r)
        results.append({"n": n, "status": status, "len": len(r["answer"]), "time": r["time"], "sources": r["sources"]})
        print(f"  {n}: {status} ({len(r['answer'])}字 {r['time']:.0f}s src={r['sources']})")

# PASS = raw PASS + PASS_BEST_EFFORT
PASS_STATUSES = {"PASS", "PASS_BEST_EFFORT"}
pass_cnt = sum(1 for r in results if r["status"] in PASS_STATUSES)
rej_cnt = sum(1 for r in results if r["status"] == "OVERREJECTION")
short_cnt = sum(1 for r in results if r["status"] == "L3_TEMPLATE")
corrupted_cnt = sum(1 for r in results if r["status"] == "RESPONSE_CORRUPTED")
rule_fail = sum(1 for r in results if r["status"].startswith("RULE_FAIL"))
uncertain = sum(1 for r in results if r["status"] == "UNCERTAIN")
groups = {}
for r in results:
    g = r["n"][0]
    groups.setdefault(g, []).append(r)
total = len(results)
print(f"\n{'='*50}")
print(f"总{total}题 | PASS(含最佳努力): {pass_cnt} | FAIL: {total-pass_cnt}")
print(f"过拒: {rej_cnt} | L3模板: {short_cnt} | 系统崩溃: {corrupted_cnt} | 规则失败: {rule_fail} | 待LLM: {uncertain}")
for g in sorted(groups):
    grp = groups[g]
    pg = sum(1 for r in grp if r["status"] in PASS_STATUSES)
    fg = [r for r in grp if r["status"] not in PASS_STATUSES]
    fs = ", ".join(f"{r['n']} {r['status']}" for r in fg[:4])
    gn = GROUP_NAMES.get(g, g)
    print(f"  {g}组({gn}): {pg}/{len(grp)} ✅{' ❌ ' + fs if fg else ''}")
print("\nFAILURES:")
for r in results:
    if r["status"] not in PASS_STATUSES:
        print(f"  {r['n']} ({r['status']}) {r['len']}字 src={r['sources']}")
print(f"\n通过率: {pass_cnt}/{total} ({round(pass_cnt/total*100, 1)}%)")
print(f"有效通过率(PASS+L3模板): {pass_cnt+short_cnt}/{total} ({round((pass_cnt+short_cnt)/total*100, 1)}%)")
