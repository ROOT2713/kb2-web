"""Phase Final: 60-question A/B evaluation with CC-generated test bank.

A: :3026 (pre-OKF baseline, f683f66 code)
B: :3027 (OKF Full: C1+C2+C3+C5+F+H+C4, commit 8e7b8f3)
Judge: DeepSeek LLM-as-Judge (same as Phase D)
"""
import json, time, jwt, requests, os, sys

# ── Config ──
SECRET = "0eA-sqLU9EbDxdXpGwOzRA8_dV7ENF2a-GOLB1mnWNMleXS-iy0TD6QhQorTB4HH"
A_URL = "http://127.0.0.1:3026/api/query"
B_URL = "http://127.0.0.1:3027/api/query"
JUDGE_URL = "https://api.deepseek.com/v1/chat/completions"
JUDGE_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
# Fallback: read from .env
if not JUDGE_KEY:
    from dotenv import load_dotenv
    load_dotenv("/home/ubuntu/kb2-web/backend/.env")
    JUDGE_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""

QUESTIONS_FILE = "/home/ubuntu/kb2-web/data/ab_eval_run/cc_60_questions.json"
RESULTS_FILE = "/home/ubuntu/kb2-web/data/ab_eval_run/results_phase_final.json"
SUMMARY_FILE = "/home/ubuntu/kb2-web/data/ab_eval_run/phase_final_summary.json"

def make_token():
    return jwt.encode(
        {"sub": "eval_final", "iat": int(time.time()), "exp": int(time.time()) + 7200},
        SECRET, algorithm="HS256"
    )

def query_endpoint(url, token, q, nocache=True):
    """Query one endpoint, return (answer, sources)."""
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"q": q, "bank": "all", "nocache": "1" if nocache else "0"},
            timeout=90,
        )
        data = r.json()
        sources = []
        for s in data.get("sources", [])[:5]:
            sources.append(s.get("doc") or "?")
        return data.get("answer", ""), sources
    except Exception as e:
        return f"[ERROR: {e}]", []

def judge_pair(q, expected_keywords, a_ans, b_ans, a_sources, b_sources, expected_docs):
    """DeepSeek judge: compare A vs B answers."""
    # Recall: check if expected docs appear in sources
    a_recall = 1 if any(any(ed.lower() in s.lower() for s in a_sources) for ed in expected_docs) else 0
    b_recall = 1 if any(any(ed.lower() in s.lower() for s in b_sources) for ed in expected_docs) else 0

    # Answer quality: 0/1/2 per side
    prompt = f"""You are evaluating two AI answers to the same question. Score each 0-2.
- 0 = wrong/irrelevant/no answer
- 1 = partially correct (mentions topic but misses key points)
- 2 = correct and comprehensive

Question: {q}
Expected keywords: {expected_keywords}

Answer A:
{a_ans[:1500]}

Answer B:
{b_ans[:1500]}

Respond in JSON:
{{"a_score": 0|1|2, "b_score": 0|1|2, "winner": "A"|"B"|"tie", "reason": "one sentence"}}
"""
    try:
        r = requests.post(
            JUDGE_URL,
            headers={
                "Authorization": f"Bearer {JUDGE_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 200,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        result = r.json()["choices"][0]["message"]["content"]
        verdict = json.loads(result)
        return {
            "a_recall": a_recall,
            "b_recall": b_recall,
            "a_score": verdict.get("a_score", 0),
            "b_score": verdict.get("b_score", 0),
            "winner": verdict.get("winner", "tie"),
            "reason": verdict.get("reason", ""),
        }
    except Exception as e:
        return {
            "a_recall": a_recall, "b_recall": b_recall,
            "a_score": 0, "b_score": 0, "winner": "tie",
            "reason": f"judge error: {e}",
        }

def main():
    with open(QUESTIONS_FILE) as f:
        questions = json.load(f)

    print(f"Loaded {len(questions)} questions")
    token = make_token()

    results = []
    for i, q_obj in enumerate(questions):
        qid = q_obj["id"]
        q = q_obj["question"]
        cat = q_obj.get("category", "")
        expected_docs = q_obj.get("expected_docs", [])
        expected_keywords = q_obj.get("expected_answer_keywords", [])

        print(f"[{i+1}/{len(questions)}] #{qid} ({cat}): {q[:50]}...", flush=True)

        a_ans, a_sources = query_endpoint(A_URL, token, q)
        b_ans, b_sources = query_endpoint(B_URL, token, q)

        verdict = judge_pair(q, expected_keywords, a_ans, b_ans, a_sources, b_sources, expected_docs)

        results.append({
            "id": qid, "category": cat, "q": q,
            "expected_docs": expected_docs,
            "expected_keywords": expected_keywords,
            "a_top5": a_sources, "b_top5": b_sources,
            "a_answer": a_ans[:2000], "b_answer": b_ans[:2000],
            **verdict,
        })

        print(f"  recall A={verdict['a_recall']} B={verdict['b_recall']} | "
              f"score A={verdict['a_score']} B={verdict['b_score']} | "
              f"winner={verdict['winner']}", flush=True)

        # Save incrementally
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        time.sleep(1)  # rate limit

    # ── Summary ──
    total = len(results)
    a_recall = sum(r["a_recall"] for r in results) / total
    b_recall = sum(r["b_recall"] for r in results) / total
    a_score = sum(r["a_score"] for r in results) / (total * 2)
    b_score = sum(r["b_score"] for r in results) / (total * 2)
    wins_b = sum(1 for r in results if r["winner"] == "B")
    wins_a = sum(1 for r in results if r["winner"] == "A")
    ties = sum(1 for r in results if r["winner"] == "tie")

    # Per-category breakdown
    cats = {}
    for r in results:
        c = r["category"]
        if c not in cats:
            cats[c] = {"n": 0, "a_score": 0, "b_score": 0, "a_recall": 0, "b_recall": 0}
        cats[c]["n"] += 1
        cats[c]["a_score"] += r["a_score"]
        cats[c]["b_score"] += r["b_score"]
        cats[c]["a_recall"] += r["a_recall"]
        cats[c]["b_recall"] += r["b_recall"]

    summary = {
        "total": total,
        "recall": {"a": round(a_recall * 100, 1), "b": round(b_recall * 100, 1),
                    "delta": round((b_recall - a_recall) * 100, 1)},
        "answer": {"a": round(a_score * 100, 1), "b": round(b_score * 100, 1),
                    "delta": round((b_score - a_score) * 100, 1)},
        "wins": {"a": wins_a, "b": wins_b, "tie": ties},
        "categories": {c: {
            "n": v["n"],
            "a_recall_pct": round(v["a_recall"] / v["n"] * 100, 1),
            "b_recall_pct": round(v["b_recall"] / v["n"] * 100, 1),
            "a_score_pct": round(v["a_score"] / (v["n"] * 2) * 100, 1),
            "b_score_pct": round(v["b_score"] / (v["n"] * 2) * 100, 1),
        } for c, v in cats.items()},
    }

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"FINAL A/B Evaluation ({total} questions)")
    print(f"{'='*60}")
    print(f"Recall:  A={summary['recall']['a']}% → B={summary['recall']['b']}% (Δ{summary['recall']['delta']:+.1f}pp)")
    print(f"Answer:  A={summary['answer']['a']}% → B={summary['answer']['b']}% (Δ{summary['answer']['delta']:+.1f}pp)")
    print(f"Wins:    A={wins_a} B={wins_b} Tie={ties}")
    print(f"\nPer-category:")
    for c, v in summary["categories"].items():
        print(f"  {c}: recall {v['a_recall_pct']}→{v['b_recall_pct']} | score {v['a_score_pct']}→{v['b_score_pct']}")

if __name__ == "__main__":
    main()
