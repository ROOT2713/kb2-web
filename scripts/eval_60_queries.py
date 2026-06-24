#!/usr/bin/env python3
"""kb2-web 60题检索质量评估"""

import json
import time
import sys
import urllib.request
import urllib.parse

API_BASE = "http://localhost:3027/api"
QUERIES = [
    # ===== Category 1: 标准号精确匹配 (Q01-Q15) =====
    ("Q01", "GB 50174 数据中心设计规范", "standards"),
    ("Q02", "GB/T 22239 等保2.0基本要求", "standards"),
    ("Q03", "GB/T 28448 等保测评要求", "standards"),
    ("Q04", "GB/T 39786 密码应用基本要求", "standards"),
    ("Q05", "GB/T 43206 密码应用测评要求", "standards"),
    ("Q06", "T/EGAG 010 监理服务规范", "standards"),
    ("Q07", "T/EGAG 011 立项设计咨询规范", "standards"),
    ("Q08", "T/EGAG 021 验收测评服务规范", "standards"),
    ("Q09", "GB 50348 安全防范工程技术标准", "standards"),
    ("Q10", "GB/T 25000.51 系统与软件质量要求和评价", "standards"),
    ("Q11", "GB 50343 建筑物防雷技术规范", "standards"),
    ("Q12", "GA/T 1127 安全防范视频监控摄像机通用技术要求", "standards"),
    ("Q13", "粤府办〔2020〕9号 省级政务信息化项目管理办法", "standards"),
    ("Q14", "GB 50462 数据中心基础设施施工及验收标准", "standards"),
    ("Q15", "GB/T 35273 个人信息安全规范", "standards"),

    # ===== Category 2: 标准标题模糊匹配 (Q16-Q25) =====
    ("Q16", "广州市政务信息化项目验收管理细则有哪些内容", "project"),
    ("Q17", "广东省政务信息化项目管理办法2023", "project"),
    ("Q18", "电子政务工程造价指导书", "project"),
    ("Q19", "省级政务信息化验收测评服务项目管理指引", "project"),
    ("Q20", "软件造价评估实施规程", "standards"),
    ("Q21", "会议系统检测实施细则", "standards"),
    ("Q22", "消防联动控制系统标准", "standards"),
    ("Q23", "火灾自动报警系统设计规范", "standards"),
    ("Q24", "视频显示系统工程技术规范", "standards"),
    ("Q25", "城市轨道交通站台屏蔽门系统技术规范", "standards"),

    # ===== Category 3: 政务管理政策 (Q26-Q35) =====
    ("Q26", "广州市政务信息化项目管理办法2022修订稿", "project"),
    ("Q27", "广州市南沙区财政投资信息化项目管理办法", "project"),
    ("Q28", "广州市南沙区财政投资信息化项目管理办法2025修订", "project"),
    ("Q29", "广州市政务信息化建设开发类项目方案编写规范", "project"),
    ("Q30", "广州市政务信息化运维服务类项目方案编写规范", "project"),
    ("Q31", "广东省省级政务信息化验收测评服务项目管理指引解读", "project"),
    ("Q32", "附件1 广东省等保测评机构检查标准", "standards"),
    ("Q33", "处置办法穗财资2022", "project"),
    ("Q34", "监理报告附表有哪些内容", "project"),
    ("Q35", "验收测评附表", "project"),

    # ===== Category 4: AI/技术方法论 (Q36-Q45) =====
    ("Q36", "RAG三种架构对比", "tech"),
    ("Q37", "RAG检索准确率从60%提升到85%的方法", "tech"),
    ("Q38", "Claude Code动态工作流", "tech"),
    ("Q39", "如何构建可交付的AI Agent系统", "tech"),
    ("Q40", "LangChain vs LangGraph适用场景", "tech"),
    ("Q41", "Supervision AI视觉方案", "tech"),
    ("Q42", "数据标注质检流程", "tech"),
    ("Q43", "数据清洗方法OpenRefine", "tech"),
    ("Q44", "OCR文档标注模板", "tech"),
    ("Q45", "标注员能力模型", "tech"),

    # ===== Category 5: 小红书/学习内容 (Q46-Q55) =====
    ("Q46", "普通人如何应对金融危机", "xhs"),
    ("Q47", "小红书开店方法论", "xhs"),
    ("Q48", "如何用Codex做期末考复习", "xhs"),
    ("Q49", "OpenAI教你如何榨干Codex", "xhs"),
    ("Q50", "三遍读论文法", "xhs"),
    ("Q51", "AI写作Prompt", "xhs"),
    ("Q52", "美股Skills蒸馏方法论", "xhs"),
    ("Q53", "3D数据可视化大屏", "xhs"),
    ("Q54", "入门LLM的训练方法", "xhs"),
    ("Q55", "Excel做RAG的好方法", "xhs"),

    # ===== Category 6: 地理+时间限定 + 边界 (Q56-Q60) =====
    ("Q56", "广州市的政务信息化验收规定", "geo"),
    ("Q57", "广东省的标准规范", "geo"),
    ("Q58", "2023年发布的验收规范", "time"),
    ("Q59", "2022年发布的广东省标准", "time"),
    ("Q60", "AirMagnet Survey使用教程", "edge"),
]


def login():
    data = json.dumps({"username": "admin", "password": "adminljj0806!"}).encode()
    req = urllib.request.Request(f"{API_BASE}/auth/login", data=data,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["access_token"]


def run_query(token, qid, question, category, timeout=60):
    data = f"q={urllib.parse.quote(question)}&bank=all&nocache=1&rerank=true".encode()
    req = urllib.request.Request(f"{API_BASE}/query", data=data,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        t0 = time.time()
        resp = urllib.request.urlopen(req, timeout=timeout)
        elapsed = time.time() - t0
        result = json.loads(resp.read())

        answer = result.get("answer", "")
        sources = result.get("sources", [])

        # Determine quality score 0-5
        score = 0
        if len(answer) > 50:
            score += 2
        if len(sources) >= 3:
            score += 2
        elif len(sources) >= 1:
            score += 1
        if len(answer) > 200:
            score += 1  # detailed answer

        return {
            "qid": qid,
            "question": question,
            "category": category,
            "answer_len": len(answer),
            "source_count": len(sources),
            "score": score,
            "elapsed": round(elapsed, 1),
            "answer_preview": answer[:120].replace("\n", " "),
            "error": None,
        }
    except Exception as e:
        return {
            "qid": qid,
            "question": question,
            "category": category,
            "answer_len": 0,
            "source_count": 0,
            "score": 0,
            "elapsed": 0,
            "answer_preview": "",
            "error": str(e)[:100],
        }


def main():
    print("=" * 80)
    print("kb2-web 60题检索质量评估")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    token = login()
    print(f"登录成功, token={token[:20]}...\n")

    results = []
    for qid, question, category in QUERIES:
        sys.stdout.write(f"  [{qid}] {question[:40]:40s} ... ")
        sys.stdout.flush()
        r = run_query(token, qid, question, category)
        results.append(r)
        status = "✓" if r["score"] >= 2 else ("△" if r["source_count"] > 0 else "✗")
        sys.stdout.write(f"{status}  sources={r['source_count']} len={r['answer_len']} score={r['score']} {r['elapsed']}s\n")
        sys.stdout.flush()
        time.sleep(0.3)  # gentle rate limit

    # Summary
    print("\n" + "=" * 80)
    print("评估汇总")
    print("=" * 80)

    categories = {}
    for r in results:
        cat = r["category"]
        categories.setdefault(cat, {"total": 0, "scored": 0, "found": 0, "score_sum": 0})
        categories[cat]["total"] += 1
        categories[cat]["scored"] += 1 if r["score"] >= 2 else 0
        categories[cat]["found"] += 1 if r["source_count"] > 0 else 0
        categories[cat]["score_sum"] += r["score"]

    print(f"\n{'类别':<15} {'总数':>5} {'评分≥2':>7} {'有来源':>7} {'均分':>5} {'通过率':>7}")
    print("-" * 50)
    all_scored = all_found = all_total = all_sum = 0
    for cat, d in sorted(categories.items()):
        avg = round(d["score_sum"] / max(d["total"], 1), 1)
        pass_rate = f"{d['scored']}/{d['total']}"
        print(f"{cat:<15} {d['total']:>5} {d['scored']:>7} {d['found']:>7} {avg:>5} {pass_rate:>7}")
        all_scored += d["scored"]
        all_found += d["found"]
        all_total += d["total"]
        all_sum += d["score_sum"]

    avg_all = round(all_sum / max(all_total, 1), 1)
    print("-" * 50)
    print(f"{'总计':<15} {all_total:>5} {all_scored:>7} {all_found:>7} {avg_all:>5} {all_scored}/{all_total}")

    # Failed queries
    fails = [r for r in results if r["score"] < 2 and r["error"] is None]
    if fails:
        print(f"\n⚠️  {len(fails)} 题得分<2（可能需要优化）:")
        for r in fails:
            print(f"  [{r['qid']}] {r['question']:50s} sources={r['source_count']} len={r['answer_len']}")

    errors = [r for r in results if r["error"]]
    if errors:
        print(f"\n❌ {len(errors)} 题请求出错:")
        for r in errors:
            print(f"  [{r['qid']}] {r['question']:50s} err={r['error']}")

    # Save full results
    report = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "total": all_total,
        "passed": all_scored,
        "avg_score": avg_all,
        "categories": categories,
        "results": results,
    }
    with open("/home/ubuntu/kb2-web/scripts/eval_60_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n完整报告已保存: scripts/eval_60_report.json")

    # Detailed table
    print(f"\n{'='*80}")
    print("逐题明细")
    print(f"{'='*80}")
    header = f"{'ID':<6} {'类别':<8} {'来源数':>6} {'长度':>6} {'分':>3} {'耗时':>5}  {'问题':<50}"
    print(header)
    print("-" * 80)
    for r in results:
        flag = "✓" if r["score"] >= 2 else ("△" if r["source_count"] > 0 else "✗")
        print(f"{r['qid']:<6} {r['category']:<8} {r['source_count']:>6} {r['answer_len']:>6} {r['score']:>3} {r['elapsed']:>5}s  {flag} {r['question'][:48]}")


if __name__ == "__main__":
    main()
