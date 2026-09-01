#!/usr/bin/env python3
"""检索质量基线 (P2') — BGE-M3 + pgvector 生产检索层指标快照。

用法（必须在 backend/ 目录运行，.env 自动加载）:
    python3 scripts/recall_quality_baseline.py --sample 30 --seed 42

逻辑（对齐生产 query_engine._build_search_context，use_rerank=False）:
    1. 从 scripts/105_questions_v7.jsonl 按 category 分层抽样 N 题
    2. 每题复刻生产参数构造（同义词扩展/金额档位/关键词）后调用
       _build_search_context() → recall(多bank) + BM25 + rrf_merge + keyword_rerank
    3. 命中判定: expected 中 "must include:" 条目拆原子短语，
       任一原子出现在 top-k chunk 文本即命中
    4. 指标: hit@5 / hit@10 / top1_hit / 按 category 聚合
    5. 落盘 baselines/bge_m3_<date>_seed<seed>.json + .csv

这是未来换 embedding（WeMM/Qwen3-VL 等）的决策标尺与回归基线。
"""

import argparse
import asyncio
import csv
import json
import logging
import random
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("app").setLevel(logging.ERROR)  # 抑制 RECALL-DEBUG/BM25 噪音

from app.services.retrieval import BANKS, build_bm25_index, expand_query_synonyms  # noqa: E402
from app.utils.text_cleaning import expand_amount_tiers  # noqa: E402
from app.utils.tokenizer import expand_keywords  # noqa: E402
import jieba  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = BASE_DIR / "105_questions_v7.jsonl"
BASELINE_DIR = BASE_DIR / "baselines"

# 进程内单例：预构建的 BM25 索引（避免每题重建 10s）
_BM25_STATE = {"bm25": None, "docs": None}


async def ensure_bm25():
    """懒构建一次 BM25 索引并缓存到进程内。返回 (bm25, docs)。"""
    if _BM25_STATE["bm25"] is None:
        _BM25_STATE["bm25"], _BM25_STATE["docs"] = await build_bm25_index("all")
    return _BM25_STATE["bm25"], _BM25_STATE["docs"]

# category 分层配额（总计 = sample 数）
CATEGORY_QUOTA = {"fact": 8, "fee": 6, "cross": 6, "open": 6, "edge": 2, "rejection": 2}

# 检索 bank：生产默认 'all'（query.py Form("all")），hs_bank = 全部 hindsight banks
DEFAULT_BANK = "all"

# 非检索类验证的 expected 标记（rejection/空输入等）—— 不参与命中率
NON_RECALL_MARKERS = ("[数据缺口]", "reject:", "must not answer", "不得回答", "拒绝回答")


def extract_keywords(expected: str) -> list:
    """提取检索层命中关键词。

    - 仅处理 'must include:' 开头的条目（'reject:'/'may include:' 等不参与检索判定）
    - 条目按 [;；\\n] 拆分，每条再按 [，,、] 拆成原子短语
    - 返回原子列表；任一原子出现在 top-k chunk 文本即命中
    """
    if "must include:" not in expected.lower():
        return []
    text = re.sub(r"^.*?must include:\s*", "", expected.strip(), flags=re.I | re.S)
    entries = [e.strip() for e in re.split(r"[;；\n]+", text) if e.strip()]
    atoms = []
    for e in entries:
        for a in re.split(r"[，,、]+", e):
            a = a.strip()
            # 丢弃过短原子（<3 字符，如 'D'、'Z'），避免子串误命中
            if len(a) >= 3:
                atoms.append(a)
    return atoms


def is_recall_valid(q: dict) -> bool:
    """该题是否参与检索命中率统计（排除 rejection / 空输入 / 非 must-include 期望）。"""
    if q.get("category") == "rejection":
        return False
    exp = q.get("expected", "")
    return "must include:" in exp.lower() and not any(
        m.lower() in exp.lower() for m in NON_RECALL_MARKERS
    )


def build_context_params(q: str) -> dict:
    """复刻 query.py L200-257 的参数构造（bank='all' 路径，无 session/kg）。"""
    bank = DEFAULT_BANK
    bank_cfg = BANKS.get(bank, {})
    hindsight_banks = bank_cfg.get("hindsight_banks") or [bank_cfg.get("hindsight")]
    hs_bank = ",".join(h for h in hindsight_banks if h)

    q_recalled = expand_query_synonyms(q)
    q_bm25 = expand_amount_tiers(q_recalled)
    _tier_extra = []
    if q_bm25 != q_recalled:
        _tier_extra = q_bm25[len(q_recalled):].strip().split()

    _q_for_kw = q_recalled
    query_keywords_raw = [w for w in jieba.cut(_q_for_kw) if len(w.strip()) > 1]
    query_keywords = expand_keywords(query_keywords_raw)
    if _tier_extra:
        query_keywords = list(set(query_keywords + _tier_extra))

    kg_info = {"matched_entities": [], "suggested_doc_ids": [], "disambiguated": False}
    return dict(
        q=q, bank=bank, history="", use_rerank=False, rerank_mode="default",
        hs_bank=hs_bank, q_recalled=q_recalled, q_bm25=q_bm25,
        query_keywords=query_keywords, _tier_extra=_tier_extra,
        kg_info=kg_info, session_doc_ids=None, categories="",
    )


def load_questions() -> list:
    qs = []
    for line in QUESTIONS_FILE.open(encoding="utf-8"):
        line = line.strip()
        if line:
            qs.append(json.loads(line))
    return qs


def stratified_sample(qs: list, seed: int) -> list:
    rng = random.Random(seed)
    by_cat = {}
    for q in qs:
        by_cat.setdefault(q["category"], []).append(q)
    picked = []
    for cat, quota in CATEGORY_QUOTA.items():
        pool = by_cat.get(cat, [])
        picked.extend(rng.sample(pool, min(quota, len(pool))))
    return picked


def hit_detection(result_chunks: list, keywords: list) -> dict:
    """判定 top-k 命中情况。返回 {hit5, hit10, top1_hit, hit_keywords}。"""
    out = {"hit5": False, "hit10": False, "top1_hit": False, "hit_keywords": []}
    if not keywords:
        return out
    for idx, chunk in enumerate(result_chunks[:10]):
        text = chunk.get("text", "") or ""
        for kw in keywords:
            if kw and kw.lower() in text.lower():
                if idx < 5:
                    out["hit5"] = True
                out["hit10"] = True
                if idx == 0:
                    out["top1_hit"] = True
                if kw not in out["hit_keywords"]:
                    out["hit_keywords"].append(kw)
    return out


async def run_one(q: dict, ctx: dict) -> dict:
    """ctx = build_context_params(q['question'])，内部复用 BM25 单例，等价生产链路。"""
    try:
        bank = ctx["bank"]
        hs_bank = ctx["hs_bank"]
        q_recalled = ctx["q_recalled"]
        q_bm25 = ctx["q_bm25"]
        query_keywords = ctx["query_keywords"]

        # ── 语义召回（多 bank 并行，同 recall() 'all' 分支）──
        from app.services.retrieval import recall
        raw_results = await recall(q_recalled, limit=25, bank=bank)

        # ── BM25 + RRF（复用单例索引，等价 _build_search_context）──
        bm25, bm25_docs = await ensure_bm25()
        bm25_hits = []
        if bm25:
            from app.services.retrieval import bm25_search
            bm25_hits = bm25_search(q_bm25, bm25, bm25_docs, top_k=30)
        merged = []
        if bm25_hits:
            from app.services.retrieval import rrf_merge
            merged = rrf_merge(raw_results, bm25_hits, k=60, query_keywords=query_keywords, bank=bank)
        else:
            merged = list(raw_results)

        # ── keyword_rerank（生产 use_rerank=False 时仍执行）──
        from app.services.retrieval import keyword_rerank
        chunks = keyword_rerank(q["question"], merged, top_k=20) if merged else []
    except Exception as e:  # noqa: BLE001
        return {"id": q["id"], "question": q["question"], "error": str(e), "chunks": []}

    keywords = extract_keywords(q.get("expected", ""))
    hits = hit_detection(chunks, keywords)
    doc_ids = set()
    for c in chunks[:10]:
        for t in c.get("tags", []):
            if t.startswith("doc_id:"):
                doc_ids.add(t[7:])
                break

    top1_score = chunks[0].get("score", 0.0) if chunks else None
    return {
        "id": q["id"], "category": q["category"], "bank_hint": q.get("bank_hint", ""),
        "question": q["question"], "expected": q.get("expected", ""),
        "keywords": keywords, "n_chunks": len(chunks), "n_docs": len(doc_ids),
        "top1_score": top1_score, **hits,
        "hit_valid": is_recall_valid(q),  # False = rejection/空输入/非 must-include，不计入命中率
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    qs = load_questions()
    picked = stratified_sample(qs, args.seed)[: args.sample]
    print(f"[baseline] 抽样 {len(picked)} 题 (seed={args.seed})，预构建 BM25 索引…")

    # 预构建一次 BM25 索引（进程内单例，后续题复用，避免每题重建 10s）
    try:
        await ensure_bm25()
        print("[baseline] BM25 索引就绪")
    except Exception as e:  # noqa: BLE001
        print(f"[baseline] BM25 构建失败（降级为纯 recall）: {e}")

    print(f"[baseline] 运行中…")

    results = []
    for i, q in enumerate(picked, 1):
        r = await run_one(q, build_context_params(q["question"]))
        results.append(r)
        flag = "✓" if (r.get("hit10") or not r.get("hit_valid")) else "✗"
        print(f"  [{i:2d}/{len(picked)}] {r['id']:6s} {r['category']:9s} "
              f"hit@5={r.get('hit5')} hit@10={r.get('hit10')} top1={r.get('top1_hit')} {flag}")

    # ── 聚合 ──
    valid = [r for r in results if r.get("hit_valid")]
    agg = {
        "overall": {
            "n": len(valid),
            "hit5": sum(r["hit5"] for r in valid) / len(valid) if valid else None,
            "hit10": sum(r["hit10"] for r in valid) / len(valid) if valid else None,
            "top1_hit": sum(r["top1_hit"] for r in valid) / len(valid) if valid else None,
            "avg_top1_score": sum(r["top1_score"] or 0 for r in results) / len(results) if results else None,
        },
        "by_category": {},
    }
    for cat in sorted({r["category"] for r in valid}):
        sub = [r for r in valid if r["category"] == cat]
        agg["by_category"][cat] = {
            "n": len(sub),
            "hit10": sum(r["hit10"] for r in sub) / len(sub) if sub else None,
            "top1_hit": sum(r["top1_hit"] for r in sub) / len(sub) if sub else None,
        }

    # ── 落盘 ──
    BASELINE_DIR.mkdir(exist_ok=True)
    fname = f"bge_m3_{date.today().strftime('%Y%m%d')}_seed{args.seed}.json"
    out_path = BASELINE_DIR / fname
    payload = {
        "engine": "bge-m3@pgvector",
        "date": date.today().isoformat(),
        "sample": args.sample, "seed": args.seed,
        "questions_file": QUESTIONS_FILE.name,
        "metrics": agg,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = BASELINE_DIR / fname.replace(".json", ".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "category", "bank_hint", "hit@5", "hit@10", "top1_hit",
                    "top1_score", "n_docs", "question", "hit_keywords"])
        for r in results:
            w.writerow([r["id"], r["category"], r["bank_hint"], r.get("hit5"),
                        r.get("hit10"), r.get("top1_hit"), r.get("top1_score"),
                        r.get("n_docs"), r["question"],
                        "/".join(r.get("hit_keywords", []))])

    print("\n" + "=" * 60)
    print(f"基线指标 (n={agg['overall']['n']} 有判定):")
    print(f"  hit@5   = {agg['overall']['hit5']:.1%}")
    print(f"  hit@10  = {agg['overall']['hit10']:.1%}")
    print(f"  top1    = {agg['overall']['top1_hit']:.1%}")
    print(f"  avg top1 score = {agg['overall']['avg_top1_score']:.4f}")
    for cat, m in agg["by_category"].items():
        print(f"  [{cat:9s}] n={m['n']:2d} hit@10={m['hit10']:.0%} top1={m['top1_hit']:.0%}")
    print(f"\n落盘: {out_path}  (+ .csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
