"""LLM-Judge: Re-evaluate open/edge test questions using DeepSeek.
Usage: python3 llm_judge.py <results.json> [questions.jsonl]
Output: <results>.llmjudged.json — corrected pass/fail with LLM evaluation"""
import json, sys, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

LLM_URL = "https://api.deepseek.com/v1/chat/completions"
LLM_KEY = "sk-c1061aca0e794bf9aa039a09c9263c5a"

OPEN_DIMENSIONS = {"open", "edge", "fee"}
REJECT_DIMENSIONS = {"rejection"}

def llm_judge(question, answer, dimension):
    """Ask LLM if the answer is satisfactory (single-word output approach)."""
    if dimension in REJECT_DIMENSIONS:
        is_rejected = any(kw in answer for kw in [
            "未找到", "没有找到", "未收录", "未提供", "无法给出",
            "未直接命中", "没有相关信息", "未涉及", "未能找到",
            "无法回答", "知识库中未找到"
        ])
        return {"status": "pass" if is_rejected else "fail", "reason": f"rej={'yes' if is_rejected else 'no'}"}

    if dimension not in OPEN_DIMENSIONS:
        return {"status": "unknown", "reason": "skip"}

    prompt = f"""判断以下KB答案是否满足用户问题。只输出单词pass或fail。

问题：{question[:200]}
答案：{answer[:1200]}

PASS条件：答案有实质性内容（引用了文档、给出了具体信息），即使不完美。
FAIL条件：答案拒答（说"未找到"/"无法回答"/"未提供"），或明显空泛无信息。

只输出一个单词。"""

    for attempt in range(2):
        try:
            body = json.dumps({
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1, "max_tokens": 8,
            }).encode()
            req = urllib.request.Request(LLM_URL, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {LLM_KEY}"})
            resp = urllib.request.urlopen(req, timeout=45)
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip().lower()
            # Extract pass/fail from response
            if "pass" in text:
                return {"status": "pass", "reason": "llm-judge"}
            elif "fail" in text:
                return {"status": "fail", "reason": "llm-judge"}
            else:
                if attempt < 1:
                    time.sleep(2)
                    continue
                return {"status": "error", "reason": f"unexpected:{text[:50]}"}
        except Exception as e:
            if attempt < 1:
                time.sleep(3)
                continue
            return {"status": "error", "reason": str(e)[:80]}
    return {"status": "error", "reason": "max-retries"}

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 llm_judge.py <results.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)
    records = data.get("results", [])
    print(f"Total records: {len(records)}")

    open_records = [r for r in records if r.get("dimension") in OPEN_DIMENSIONS]
    print(f"Open/Edge/Fee records to re-evaluate: {len(open_records)}")

    judged = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {}
        for r in open_records:
            fut = pool.submit(llm_judge,
                r.get("query", ""),
                r.get("answer_preview", r.get("answer", "")),
                r.get("dimension", ""))
            futures[fut] = r
        for fut in as_completed(futures):
            r = futures[fut]
            result = fut.result()
            old = r.get("status", "?")
            r["llm_status"] = result["status"]
            r["llm_reason"] = result["reason"]
            judged.append(r)
            print(f"  {r.get('id','?'):6s} | {old:4s}→{result['status']:4s} | {result.get('reason','')[:40]}")

    # Merge back
    for i, r in enumerate(records):
        for jr in judged:
            if r.get("id") == jr.get("id"):
                records[i] = jr
                break

    passed = sum(1 for r in records if r.get("llm_status", r.get("status")) in ("pass", "unknown"))
    failed = sum(1 for r in records if r.get("llm_status", r.get("status")) == "fail")
    errored = sum(1 for r in records if r.get("llm_status") == "error")
    print(f"\nLLM-Judge: {passed} pass / {failed} fail / {errored} error out of {len(records)}")

    out_path = sys.argv[1].replace(".json", ".llmjudged.json")
    with open(out_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()
