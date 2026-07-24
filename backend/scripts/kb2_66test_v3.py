#!/usr/bin/env python3
"""kb2-web test runner V3-FINAL — keyword-based judge, no LLM calls
Usage: python3 kb2_66test_v3.py <questions.jsonl> [concurrency=3]
Output: /tmp/kb2_v4_results_<timestamp>.json
"""
import json, subprocess, sys, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE = "http://localhost:3027"
TOKEN = None
OUTPUT_FILE = None
CI_MODE = False

REJECT_KEYWORDS = ["未找到", "没有找到", "未收录", "未提供", "无法给出",
                   "未直接命中", "没有相关信息", "未涉及", "未能找到",
                   "无法回答", "知识库中未找到"]

def get_token():
    global TOKEN
    if TOKEN: return TOKEN
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE}/api/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"username":"admin","password":"adminljj0806!"}'],
        capture_output=True, text=True, timeout=15)
    TOKEN = json.loads(r.stdout)['access_token']
    return TOKEN

def query_kb(q, timeout=120):
    token = get_token()
    cmd = ["curl", "-s", "-X", "POST", f"{BASE}/api/query",
           "-H", f"Authorization: Bearer {token}",
           "--data-urlencode", f"q={q}",
           "--data-urlencode", "nocache=true",
           "--data-urlencode", "rerank=true",
           "--max-time", str(timeout)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+10)
        if not r.stdout.strip(): return None, []
        d = json.loads(r.stdout)
        return d.get('answer', ''), d.get('sources', [])
    except: return None, []

def is_rejected(answer):
    return any(kw in answer for kw in REJECT_KEYWORDS)

def keyword_judge(answer, expected_text, query, dimension):
    """Judge answer by keyword matching — no LLM needed."""
    # Rejection questions
    if dimension == 'rejection':
        if is_rejected(answer):
            return True, "正确拒答"
        else:
            return False, "未正确拒答"

    # If KB itself rejected, that's a fail for non-rejection questions
    if is_rejected(answer):
        return False, "KB不应拒答此问题"

    # Extract keywords from expected
    keywords = []
    exp = expected_text
    if exp.startswith('must include:'):
        exp = exp[len('must include:'):].strip()
    
    # Parse comma or comma-like separated keywords
    for kw in re.split(r'[,，、]', exp):
        kw = kw.strip()
        if kw and len(kw) >= 2:
            keywords.append(kw)
    
    if not keywords:
        # Fallback: use first meaningful part
        keywords = [exp.split()[0]]
    
    # Check each keyword
    hits = sum(1 for kw in keywords if kw in answer)
    if hits >= max(1, len(keywords) // 2):
        return True, f"关键词命中 {hits}/{len(keywords)}"
    
    # For standard numbers (GB/T XXX), be more lenient
    std_match = re.search(r'[A-Z]+[\s/]*T?[\s/]*[\d]+[\-\d]*', exp)
    if std_match:
        std = std_match.group().replace(' ', '').replace('/', '')
        if std in answer.replace(' ', ''):
            return True, f"标准号命中: {std}"
    
    return False, f"关键词 {keywords[:3]} 未在答案中"

def run_one(q_item):
    qid = q_item['id']
    query = q_item.get('query') or q_item.get('question', '')
    expected = q_item.get('expected', '')
    dimension = q_item.get('dimension') or q_item.get('category', '')
    difficulty = q_item.get('difficulty', '')
    t0 = time.time()
    
    answer, sources = query_kb(query)
    elapsed = time.time() - t0
    
    if answer is None:
        return {
            "id": qid, "query": query, "expected": expected,
            "status": "error", "score": 0, "answer_len": 0,
            "sources": 0, "judge_reason": "Query failed",
            "time": elapsed, "dimension": dimension, "difficulty": difficulty,
        }
    
    judge_pass, judge_reason = keyword_judge(answer, expected, query, dimension)
    status = "pass" if judge_pass else "fail"
    score = 8 if judge_pass else 2
    
    return {
        "id": qid, "query": query, "expected": expected,
        "answer_len": len(answer),
        "sources": len(sources) if isinstance(sources, list) else 0,
        "answer_preview": answer[:300],
        "status": status, "score": score,
        "judge_reason": judge_reason,
        "time": elapsed,
        "dimension": dimension, "difficulty": difficulty,
    }

def main():
    global OUTPUT_FILE, CI_MODE
    CI_MODE = "--ci" in sys.argv
    if CI_MODE:
        sys.argv.remove("--ci")
    if len(sys.argv) < 2:
        print("Usage: python3 kb2_66test_v3.py <questions.jsonl> [concurrency=3] [--ci]", flush=True)
        sys.exit(1)
    
    jsonl_path = sys.argv[1]
    concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    
    questions = [json.loads(l) for l in open(jsonl_path, encoding='utf-8') if l.strip()]
    total = len(questions)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    OUTPUT_FILE = f"/tmp/kb2_v4_results_{ts}.json"
    
    print(f"Loaded {total} questions, concurrency={concurrency}, output={OUTPUT_FILE}", flush=True)
    
    try:
        get_token()
        print("Service OK", flush=True)
    except Exception as e:
        print(f"Service failed: {e}", flush=True)
        sys.exit(1)
    
    results = []
    t_start = time.time()
    
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_one, q): q for q in questions}
        for i, f in enumerate(as_completed(futures)):
            try:
                r = f.result()
                results.append(r)
                sym = {"pass": "✅", "fail": "⚠️", "error": "💥"}[r['status']]
                print(f"  [{r['id']}] {sym} {r['dimension'][:4]} s={r['score']} | {r['answer_len']:>4}字 {r['sources']}src {r['time']:.0f}s | {r['judge_reason'][:40]}", flush=True)
            except Exception as e:
                print(f"  [{i}] ERROR: {e}", flush=True)
            
            if (i+1) % 10 == 0:
                _save(results, t_start, time.time()-t_start, total, done=i+1, partial=True)
    
    _save(results, t_start, time.time()-t_start, total)
    if CI_MODE:
        pass  # _save's _ci_check handles exit code

def _save(results, t_start, t_total, total, done=None, partial=False):
    by_status = {}
    by_dimension = {}
    pass_c = 0
    for r in results:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1
        if r['status'] == 'pass': pass_c += 1
        dim = r.get('dimension', 'unknown')
        if dim not in by_dimension:
            by_dimension[dim] = {"pass": 0, "fail": 0, "total": 0}
        by_dimension[dim]["total"] += 1
        if r['status'] == 'pass':
            by_dimension[dim]["pass"] += 1
        else:
            by_dimension[dim]["fail"] += 1
    
    rate = pass_c / total * 100
    
    if not partial:
        print(f"\n{'='*60}", flush=True)
        print(f"Results: {total}题, {t_total:.0f}s ({t_total/60:.1f}min)", flush=True)
        print(f"Pass: {pass_c}/{total} = {rate:.0f}%", flush=True)
        print(f"Status: {json.dumps(by_status, ensure_ascii=False)}", flush=True)
        print(f"\nBy dimension:", flush=True)
        for dim, stats in sorted(by_dimension.items()):
            dr = stats["pass"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {dim}: {stats['pass']}/{stats['total']} = {dr:.0f}%", flush=True)
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump({
            "results": sorted(results, key=lambda x: x['id']),
            "total": total, "pass_rate": rate,
            "by_status": by_status, "by_dimension": by_dimension,
            "duration": t_total, "partial": partial,
        }, f, ensure_ascii=False, indent=2)
    if partial and done is not None:
        print(f"  [partial] {done}/{total}, pass={rate:.0f}%", flush=True)
    elif not partial:
        print(f"\nSaved: {OUTPUT_FILE}", flush=True)
        # ── CI mode: write history and check for regression ──
        _ci_check(rate, total, pass_c)

def _ci_check(rate, total, pass_c):
    """CI mode: write evaluation history, exit with code 1 if pass rate dropped >5%."""
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    history_path = os.path.join(script_dir, "..", "..", ".evaluation_history.json")
    hist = {}
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                hist = json.load(f)
        except Exception:
            pass
    prev_rate = hist.get("last_pass_rate", 100.0)
    if prev_rate > rate and (prev_rate - rate) > 5:
        print(f"\n❌ CI FAILED: pass rate dropped {prev_rate:.0f}% -> {rate:.0f}% (drop >5%)", flush=True)
        sys.exit(1)
    else:
        print(f"\n✅ CI PASSED: pass rate {prev_rate:.0f}% -> {rate:.0f}%", flush=True)
    # Write new history
    json.dump({
        "last_run": datetime.now().isoformat(),
        "last_pass_rate": rate,
        "total": total,
        "pass_count": pass_c,
        "prev_pass_rate": prev_rate,
    }, open(history_path, "w"), ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
