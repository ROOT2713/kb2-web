#!/usr/bin/env python3
import requests, json, time, sys

V1 = "http://localhost:3002"
V2 = "http://localhost:3027"

# Login v2
login = requests.post(f"{V2}/api/auth/login", json={"username":"admin","password":"adminljj0806!"})
token = login.json()["access_token"]
headers_v2 = {"Authorization": f"Bearer {token}"}

queries = [
    "知识库系统", "验收测评服务规范", "GB/T 22239 等保测评",
    "500万软件项目的取费标准", "政务信息化项目管理办法",
    "电子会议系统工程施工", "数据中心基础设施",
    "信息安全等级保护", "软件造价评估方法", "安防工程设计施工规范"
]

results = []

for i, q in enumerate(queries):
    print(f"[{i+1}/10] Testing: {q}", file=sys.stderr)
    row = {"query": q}
    
    # V1
    try:
        t0 = time.time()
        r1 = requests.post(f"{V1}/api/query", data={"q": q, "bank": "all"}, timeout=120)
        t1 = time.time()
        d1 = r1.json()
        row["v1_status"] = r1.status_code
        row["v1_time"] = round(t1 - t0, 2)
        row["v1_answer_len"] = len(d1.get("answer", ""))
        row["v1_sources"] = len(d1.get("sources", []))
        row["v1_top_source"] = d1["sources"][0]["doc"] if d1.get("sources") else "N/A"
        row["v1_top_score"] = d1["sources"][0].get("score", 0) if d1.get("sources") else 0
        row["v1_answer_preview"] = d1.get("answer", "")[:150]
        row["v1_cache"] = d1.get("cache_hit", "miss")
    except Exception as e:
        row["v1_status"] = "error"
        row["v1_time"] = 0
        row["v1_error"] = str(e)
    
    # V2
    try:
        t0 = time.time()
        r2 = requests.post(f"{V2}/api/query", data={"q": q, "bank": "all", "nocache": "true"}, headers=headers_v2, timeout=120)
        t1 = time.time()
        d2 = r2.json()
        row["v2_status"] = r2.status_code
        row["v2_time"] = round(t1 - t0, 2)
        row["v2_answer_len"] = len(d2.get("answer", ""))
        row["v2_sources"] = len(d2.get("sources", []))
        row["v2_top_source"] = d2["sources"][0]["doc"] if d2.get("sources") else "N/A"
        row["v2_top_score"] = d2["sources"][0].get("score", 0) if d2.get("sources") else 0
        row["v2_answer_preview"] = d2.get("answer", "")[:150]
        row["v2_cache"] = d2.get("cache_hit", "miss")
    except Exception as e:
        row["v2_status"] = "error"
        row["v2_time"] = 0
        row["v2_error"] = str(e)
    
    results.append(row)

# Output
json.dump(results, open("/home/ubuntu/kb2-web/docs/ab-results.json", "w"), ensure_ascii=False, indent=2)

# Generate markdown report
lines = []
lines.append("# kb2-web v1 vs v2 A/B 对比测试报告")
lines.append("")
lines.append(f"**测试时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
lines.append(f"**v1地址**: {V1} (无认证)")
lines.append(f"**v2地址**: {V2} (JWT认证)")
lines.append(f"**测试查询数**: {len(queries)}")
lines.append(f"**v2参数**: nocache=true (强制绕过缓存)")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 总体对比")
lines.append("")

v1_times = [r["v1_time"] for r in results if r.get("v1_status") == 200]
v2_times = [r["v2_time"] for r in results if r.get("v2_status") == 200]
v1_lens = [r["v1_answer_len"] for r in results if r.get("v1_status") == 200]
v2_lens = [r["v2_answer_len"] for r in results if r.get("v2_status") == 200]
v1_srcs = [r["v1_sources"] for r in results if r.get("v1_status") == 200]
v2_srcs = [r["v2_sources"] for r in results if r.get("v2_status") == 200]

lines.append("| 指标 | v1 | v2 | 差异 |")
lines.append("|------|-----|-----|------|")
lines.append(f"| 成功率 | {sum(1 for r in results if r.get('v1_status')==200)}/{len(results)} | {sum(1 for r in results if r.get('v2_status')==200)}/{len(results)} | - |")
if v1_times and v2_times:
    lines.append(f"| 平均响应时间 | {sum(v1_times)/len(v1_times):.2f}s | {sum(v2_times)/len(v2_times):.2f}s | {((sum(v2_times)/len(v2_times))/(sum(v1_times)/len(v1_times))-1)*100:+.1f}% |")
    lines.append(f"| 最快响应 | {min(v1_times):.2f}s | {min(v2_times):.2f}s | - |")
    lines.append(f"| 最慢响应 | {max(v1_times):.2f}s | {max(v2_times):.2f}s | - |")
if v1_lens and v2_lens:
    lines.append(f"| 平均回答长度 | {sum(v1_lens)/len(v1_lens):.0f}字 | {sum(v2_lens)/len(v2_lens):.0f}字 | {((sum(v2_lens)/len(v2_lens))/(sum(v1_lens)/len(v1_lens))-1)*100:+.1f}% |")
if v1_srcs and v2_srcs:
    lines.append(f"| 平均来源数 | {sum(v1_srcs)/len(v1_srcs):.1f} | {sum(v2_srcs)/len(v2_srcs):.1f} | - |")

lines.append("")
lines.append("---")
lines.append("")
lines.append("## 逐项测试结果")
lines.append("")

for i, r in enumerate(results):
    lines.append(f"### {i+1}. {r['query']}")
    lines.append("")
    lines.append("| 维度 | v1 | v2 |")
    lines.append("|------|-----|-----|")
    v1s = r.get("v1_status", "err")
    v2s = r.get("v2_status", "err")
    lines.append(f"| HTTP状态 | {v1s} | {v2s} |")
    lines.append(f"| 响应时间 | {r.get('v1_time','N/A')}s | {r.get('v2_time','N/A')}s |")
    lines.append(f"| 回答长度 | {r.get('v1_answer_len','N/A')}字 | {r.get('v2_answer_len','N/A')}字 |")
    lines.append(f"| 来源数量 | {r.get('v1_sources','N/A')} | {r.get('v2_sources','N/A')} |")
    lines.append(f"| Top来源 | {r.get('v1_top_source','N/A')[:40]} | {r.get('v2_top_source','N/A')[:40]} |")
    lines.append(f"| Top分数 | {r.get('v1_top_score','N/A')} | {r.get('v2_top_score','N/A')} |")
    lines.append(f"| 缓存状态 | {r.get('v1_cache','N/A')} | {r.get('v2_cache','N/A')} |")
    
    # Compare answer quality
    v1a = r.get("v1_answer_preview", "")
    v2a = r.get("v2_answer_preview", "")
    if v1a and v2a:
        lines.append("")
        lines.append(f"**v1回答片段**: {v1a[:100]}...")
        lines.append("")
        lines.append(f"**v2回答片段**: {v2a[:100]}...")
    
    # Winner
    v1_score = r.get("v1_answer_len", 0) * 0.3 + r.get("v1_sources", 0) * 100 * 0.3 + r.get("v1_top_score", 0) * 1000 * 0.4
    v2_score = r.get("v2_answer_len", 0) * 0.3 + r.get("v2_sources", 0) * 100 * 0.3 + r.get("v2_top_score", 0) * 1000 * 0.4
    winner = "v2 ✅" if v2_score > v1_score else ("v1 ✅" if v1_score > v2_score else "平局 🤝")
    lines.append(f"\n**综合评判**: {winner}")
    lines.append("")

lines.append("---")
lines.append("")
lines.append("## 结论")
lines.append("")

v1_wins = sum(1 for r in results if r.get("v1_answer_len",0)*0.3 + r.get("v1_sources",0)*100*0.3 + r.get("v1_top_score",0)*1000*0.4 > r.get("v2_answer_len",0)*0.3 + r.get("v2_sources",0)*100*0.3 + r.get("v2_top_score",0)*1000*0.4)
v2_wins = len(results) - v1_wins
lines.append(f"- **v1胜出**: {v1_wins}项")
lines.append(f"- **v2胜出**: {v2_wins}项")
lines.append(f"- v2使用nocache=true强制绕过缓存，测试检索能力")
lines.append(f"- v2增加了JWT认证层，安全性更高")
if v1_times and v2_times:
    avg_diff = (sum(v2_times)/len(v2_times)) - (sum(v1_times)/len(v1_times))
    lines.append(f"- 响应时间差异: v2平均{'慢' if avg_diff>0 else '快'} {abs(avg_diff):.2f}s")
lines.append("")

report = "\n".join(lines)
with open("/home/ubuntu/kb2-web/docs/ab-comparison.md", "w") as f:
    f.write(report)

print("Report generated: /home/ubuntu/kb2-web/docs/ab-comparison.md")
print(json.dumps({"v1_wins": v1_wins, "v2_wins": v2_wins, "avg_v1_time": sum(v1_times)/len(v1_times) if v1_times else 0, "avg_v2_time": sum(v2_times)/len(v2_times) if v2_times else 0}, indent=2))
