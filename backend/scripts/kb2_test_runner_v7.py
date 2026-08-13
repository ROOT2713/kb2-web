#!/usr/bin/env python3
"""kb2-web v7 测试集完整过程运行器 — 记录提问/回答/来源/判题/过程信号/分析/研判

按 docs/test-run-process-prompt.md 的要求实现。输出：
1. /tmp/test_results_v7.jsonl — 每题完整过程记录
2. /tmp/test_report_v7.md — 人类可读分析报告

用法: python3 scripts/kb2_test_runner_v7.py [--limit N] [--category fee]
"""
import json
import os
import re
import sys
import time
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://localhost:3027"
RESULT_FILE = "/tmp/test_results_v7.jsonl"
REPORT_FILE = "/tmp/test_report_v7.md"

# 费表文档关键词（用于识别费用类来源）
FEE_DOC_KW = ["造价", "东莞", "佛山", "指导书", "概算", "取费", "计费"]
REJECT_KW = ["未找到", "知识库中未找到", "无法回答", "没有足够的信息"]


def get_token():
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE}/api/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"username":"admin","password":"adminljj0806!"}'],
        capture_output=True, text=True, timeout=15)
    try:
        return json.loads(r.stdout).get("access_token", "")
    except Exception:
        return ""


def query_one(q: str, token: str) -> dict:
    """调用 /api/query，返回完整响应 + 元信息"""
    start = time.time()
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BASE}/api/query",
             "-H", f"Authorization: Bearer {token}",
             "--data-urlencode", f"q={q}",
             "--data-urlencode", "nocache=true",
             "--data-urlencode", "bank=all",
             "-m", "120"],
            capture_output=True, text=True, timeout=130)
        elapsed = time.time() - start
        status_code = "timeout" if r.returncode != 0 else "ok"
        try:
            d = json.loads(r.stdout)
            return {"status": status_code, "elapsed_ms": int(elapsed * 1000),
                    "response": d}
        except json.JSONDecodeError:
            return {"status": "parse_error", "elapsed_ms": int(elapsed * 1000),
                    "raw": r.stdout[:500], "response": {}}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "elapsed_ms": 120000, "response": {}}


def _normalize_text(t: str) -> str:
    """归一化：去空格/全角转半角/常见等价符号统一，提高判题宽容度"""
    t = re.sub(r"\s+", "", t)
    # 全角→半角
    t = t.replace("（", "(").replace("）", ")").replace("，", ",").replace("：", ":")
    t = t.replace("．", ".").replace("％", "%").replace("－", "-").replace("～", "~")
    # 等价符号统一
    t = t.replace("×", "x").replace("＊", "x").replace("*", "x")
    t = t.replace("≤", "<=").replace("≥", ">=").replace("＜", "<").replace("＞", ">")
    t = t.replace("＝", "=")
    return t.lower()


def _extract_core_terms(phrase: str) -> list:
    """从期望短语提取核心匹配词：数字+单位组合、纯数字、≥2字关键词。
    如 '昼间60dB' → ['60dB']；'D≤500 g≥3.0% Z≤0' → ['D≤500','g≥3.0%','Z≤0']
    用于宽松匹配，避免整串子串匹配的假阴性。
    """
    terms = []
    # 1. 数字+单位组合 (60dB, 3.0%, 2.8%, 500万, 1.2-1.4s, 24±1℃)
    for m in re.findall(r"[\d\.\-～±~]+[a-zA-Z%℃万s]?", phrase):
        if len(m) >= 2:
            terms.append(m)
    # 2. 纯数字（保留有意义长度）
    for m in re.findall(r"\d{1,4}", phrase):
        if len(m) >= 2:
            terms.append(m)
    # 3. 中文关键词（≥2字，过滤常见虚词/标点）
    for m in re.findall(r"[\u4e00-\u9fff]{2,}", phrase):
        if m not in ("需要", "应该", "可以", "包括", "分别", "应该按"):
            terms.append(m)
    return terms


def judge(item: dict, resp: dict) -> dict:
    """三级判题：keyword + semantic + fee 专项"""
    answer = resp.get("answer", "") or ""
    sources = resp.get("sources", []) or []
    expected = item.get("expected", "")

    # 1. 拒答检测
    rejected = any(kw in answer[:200] for kw in REJECT_KW)

    # 2. keyword 命中（must include 部分）— 宽松匹配
    must_parts = []
    if "must include:" in expected:
        must_raw = expected.split("must include:")[1].split(";")[0]
        must_parts = [p.strip() for p in must_raw.split(",") if p.strip()]

    # 对每个 must 短语：整串命中 或 核心词多数命中 都算过
    ans_norm = _normalize_text(answer)
    hit_parts, miss_parts = [], []
    for part in must_parts:
        if part in answer or _normalize_text(part) in ans_norm:
            hit_parts.append(part)
            continue
        # 宽松：核心词匹配率 ≥ 60%
        terms = _extract_core_terms(part)
        if not terms:
            hit_parts.append(part)  # 无核心词（纯虚词）视为通过
            continue
        hit_terms = [t for t in terms if t in answer or _normalize_text(t) in ans_norm]
        if len(hit_terms) / len(terms) >= 0.6:
            hit_parts.append(part)
        else:
            miss_parts.append(part)

    kw_pass = len(miss_parts) == 0 and len(must_parts) > 0

    # 3. 过程信号
    has_table = "|---" in answer or "| :---" in answer
    fee_sources = [s for s in sources
                   if any(k in (s.get("doc", "") or "") for k in FEE_DOC_KW)]
    has_mojibake = bool(re.search(r"[ÃÂåäçè]", answer[:500]))

    # 4. 判定
    if rejected and item.get("category") == "rejection":
        verdict = "PASS"  # rejection 类预期拒答
        reason = "正确拒答"
    elif rejected:
        verdict = "FAIL"
        reason = f"拒答（命中: {hit_parts[:3]}，漏: {miss_parts[:3]}）"
    elif kw_pass:
        verdict = "PASS"
        reason = f"期望短语全部命中 ({len(hit_parts)}/{len(must_parts)})"
    elif len(hit_parts) >= max(1, len(must_parts) // 2):
        verdict = "BOUNDARY"
        reason = f"部分命中 ({len(hit_parts)}/{len(must_parts)})，漏: {miss_parts[:4]}"
    else:
        verdict = "FAIL"
        reason = f"关键内容缺失，命中: {hit_parts[:3]}，漏: {miss_parts[:5]}"

    return {
        "verdict": verdict,
        "reason": reason,
        "rejected": rejected,
        "hit_keywords": hit_parts,
        "miss_keywords": miss_parts,
        "has_table": has_table,
        "fee_source_count": len(fee_sources),
        "has_mojibake": has_mojibake,
        "answer_len": len(answer),
        "source_count": len(sources),
    }


def run_one(item: dict, token: str) -> dict:
    q = item.get("question") or item.get("query") or ""
    resp_meta = query_one(q, token)
    resp = resp_meta.get("response", {})

    record = {
        "id": item.get("id", "?"),
        "category": item.get("category", "?"),
        "difficulty": item.get("difficulty", "?"),
        "question": q,
        "expected": item.get("expected", ""),
        "elapsed_ms": resp_meta.get("elapsed_ms", 0),
        "http_status": resp_meta.get("status", "?"),
        "answer": (resp.get("answer", "") or "")[:3000],
        "sources": [
            {"doc": s.get("doc", ""), "score": s.get("score"),
             "kw": s.get("keyword_matches", 0),
             "fee_tier": s.get("fee_tier", "")}
            for s in (resp.get("sources", []) or [])[:12]
        ],
        "judge": judge(item, resp),
    }
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    parser.add_argument("--category", default="", help="只跑指定 category")
    parser.add_argument("--testset", default="scripts/105_questions_v7.jsonl")
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()

    with open(args.testset) as f:
        items = [json.loads(l) for l in f if l.strip()]

    if args.category:
        items = [i for i in items if i.get("category") == args.category]
    if args.limit:
        items = items[:args.limit]

    print(f"测试集: {args.testset}  本次执行: {len(items)} 题 (并发={args.concurrency})")
    token = get_token()
    if not token:
        print("❌ 无法获取 token")
        sys.exit(1)

    records = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(run_one, item, token): item for item in items}
        done = 0
        for fut in as_completed(futs):
            item = futs[fut]
            try:
                rec = fut.result()
                records.append(rec)
                done += 1
                j = rec["judge"]
                print(f"[{done:3d}/{len(items)}] {rec['id']:10s} "
                      f"{rec['category']:10s} {j['verdict']:8s} "
                      f"len={j['answer_len']:5d} src={j['source_count']:2d} "
                      f"fee_src={j['fee_source_count']} tbl={j['has_table']} "
                      f"t={rec['elapsed_ms']/1000:.1f}s  {j['reason'][:60]}")
            except Exception as e:
                print(f"[{done+1:3d}/{len(items)}] {item.get('id','?')} ❌ 异常: {e}")

    # 写 JSONL
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n✅ 完整过程已保存: {RESULT_FILE} ({len(records)} 题)")

    # 汇总统计
    write_report(records, args.testset)


def write_report(records, testset):
    cats = {}
    verdicts = {"PASS": 0, "FAIL": 0, "BOUNDARY": 0}
    fail_reasons = {}
    fee_records = []

    for r in records:
        c = r["category"]
        cats.setdefault(c, {"PASS": 0, "FAIL": 0, "BOUNDARY": 0, "total": 0})
        cats[c]["total"] += 1
        cats[c][r["judge"]["verdict"]] += 1
        verdicts[r["judge"]["verdict"]] += 1
        if r["judge"]["verdict"] == "FAIL":
            # 归因
            if r["judge"]["rejected"]:
                cause = "拒答"
            elif r["judge"]["has_mojibake"]:
                cause = "编码"
            elif r["judge"]["source_count"] == 0:
                cause = "无来源"
            else:
                cause = "内容缺失"
            fail_reasons[cause] = fail_reasons.get(cause, 0) + 1
        if c == "fee":
            fee_records.append(r)

    total = len(records)
    pass_rate = verdicts["PASS"] / total * 100 if total else 0

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# kb2-web 测试集完整过程报告\n\n")
        f.write(f"测试集: `{testset}`  |  执行题数: {total}\n\n")
        f.write(f"## 一、三分类统计\n\n")
        f.write(f"| 判定 | 数量 | 占比 |\n|---|---|---|\n")
        f.write(f"| PASS | {verdicts['PASS']} | {verdicts['PASS']/total*100:.1f}% |\n")
        f.write(f"| BOUNDARY | {verdicts['BOUNDARY']} | {verdicts['BOUNDARY']/total*100:.1f}% |\n")
        f.write(f"| FAIL | {verdicts['FAIL']} | {verdicts['FAIL']/total*100:.1f}% |\n")
        f.write(f"| **通过率** | | **{pass_rate:.1f}%** |\n\n")

        f.write(f"## 二、按类别统计\n\n")
        f.write(f"| 类别 | 总数 | PASS | BOUNDARY | FAIL |\n|---|---|---|---|---|\n")
        for c, s in sorted(cats.items()):
            f.write(f"| {c} | {s['total']} | {s['PASS']} | {s['BOUNDARY']} | {s['FAIL']} |\n")

        f.write(f"\n## 三、失败归因\n\n")
        f.write(f"| 归因 | 数量 |\n|---|---|\n")
        for cause, n in sorted(fail_reasons.items(), key=lambda x: -x[1]):
            f.write(f"| {cause} | {n} |\n")

        f.write(f"\n## 四、费用类专项研判\n\n")
        f.write(f"fee 类题目: {len(fee_records)} 题\n\n")
        f.write(f"| ID | 判定 | 费表来源数 | 表格输出 | 说明 |\n|---|---|---|---|---|\n")
        for r in fee_records:
            j = r["judge"]
            f.write(f"| {r['id']} | {j['verdict']} | {j['fee_source_count']} | "
                    f"{'✅' if j['has_table'] else '❌'} | {j['reason'][:50]} |\n")

        f.write(f"\n## 五、失败题明细\n\n")
        for r in records:
            if r["judge"]["verdict"] == "FAIL":
                f.write(f"### {r['id']} [{r['category']}] {r['question'][:60]}\n")
                f.write(f"- 判定: {r['judge']['reason']}\n")
                f.write(f"- 来源数: {r['judge']['source_count']}, 回答长度: {r['judge']['answer_len']}\n")
                f.write(f"- 回答片段: {(r['answer'] or '')[:200]}\n\n")

        f.write(f"\n## 六、过程信号汇总\n\n")
        tbl_rate = sum(1 for r in records if r["judge"]["has_table"]) / total * 100
        moji = sum(1 for r in records if r["judge"]["has_mojibake"])
        rej = sum(1 for r in records if r["judge"]["rejected"])
        f.write(f"- 表格输出率: {tbl_rate:.1f}%\n")
        f.write(f"- 乱码出现: {moji} 题\n")
        f.write(f"- 拒答出现: {rej} 题\n")
        avg_t = sum(r["elapsed_ms"] for r in records) / max(total, 1) / 1000
        f.write(f"- 平均耗时: {avg_t:.1f}s/题\n")

    print(f"✅ 分析报告已生成: {REPORT_FILE}")


if __name__ == "__main__":
    main()
