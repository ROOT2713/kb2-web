"""
kb2-web 回归对比工具 — 比较两次运行（如：改造前 vs 改造后）的黄金查询结果。

用法：
  # 首次：运行测试生成基线快照
  pytest -s --run-integration tests/unit/test_regression_retrieval.py
  
  # 改造后：再次运行，生成新快照（建议备份 baseline 目录）
  mv regression_snapshots regression_snapshots.baseline
  pytest -s --run-integration tests/unit/test_regression_retrieval.py

  # 对比
  python scripts/compare_regression.py
"""

import json
import sys
from pathlib import Path


def load_snapshots(directory: Path) -> dict:
    """Load all JSON snapshots from a directory, keyed by query id."""
    snapshots = {}
    if not directory.exists():
        return snapshots
    for fp in sorted(directory.glob("Q*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        snapshots[data["id"]] = data
    return snapshots


def compute_metrics(baseline: dict, current: dict) -> dict:
    """Compare two snapshots and compute overlap metrics."""

    base_ids = set(baseline.get("top10_doc_ids", []))
    curr_ids = set(current.get("top10_doc_ids", []))

    # Remove None
    base_ids.discard(None)
    curr_ids.discard(None)

    if not base_ids and not curr_ids:
        return {"overlap_count": 0, "overlap_pct": 100.0, "regression": False}

    overlap = base_ids & curr_ids
    overlap_pct = len(overlap) / max(len(base_ids), 1) * 100

    # Regression = less than 60% overlap in top-10
    return {
        "overlap_count": len(overlap),
        "base_count": len(base_ids),
        "curr_count": len(curr_ids),
        "overlap_pct": round(overlap_pct, 1),
        "regression": overlap_pct < 60.0,
        "lost": sorted(base_ids - curr_ids),
        "gained": sorted(curr_ids - base_ids),
    }


def main(baseline_dir: str = "regression_snapshots.baseline",
         current_dir: str = "regression_snapshots"):
    """Compare baseline vs current snapshots and report regressions."""

    base_dir = Path(__file__).parent.parent / baseline_dir
    curr_dir = Path(__file__).parent.parent / current_dir

    baseline = load_snapshots(base_dir)
    current = load_snapshots(curr_dir)

    if not baseline:
        print(f"[对比] 未找到基线快照（{base_dir}），跳过对比。")
        print("  首次运行：pytest -s --run-integration ...")
        return

    if not current:
        print(f"[对比] 未找到当前快照（{curr_dir}）。")
        print("  请先运行测试生成当前快照。")
        return

    all_ids = sorted(set(baseline.keys()) | set(current.keys()))
    regressions = []
    total_overlap = 0
    total_base_docs = 0

    print(f"\n{'=' * 72}")
    print(f"  kb2-web 检索回归对比报告")
    print(f"  基线: {base_dir}")
    print(f"  当前: {curr_dir}")
    print(f"{'=' * 72}\n")

    print(f"{'ID':6s} {'Overlap%':9s} {'Overlap':7s} {'Base':5s} {'Now':5s}  {'Category':20s}")
    print(f"{'-'*6} {'-'*9} {'-'*7} {'-'*5} {'-'*5}  {'-'*20}")

    for qid in all_ids:
        base_q = baseline.get(qid)
        curr_q = current.get(qid)

        if not base_q or not curr_q:
            status = "❌ 缺失" if not base_q else "➕ 新增"
            print(f"{qid:6s} {'N/A':>9s} {'N/A':>7s} {'N/A':>5s} {'N/A':>5s}  {status}")
            continue

        metrics = compute_metrics(base_q, curr_q)
        total_overlap += metrics["overlap_count"]
        total_base_docs += metrics["base_count"]

        status = "🟢" if not metrics["regression"] else "🔴"
        print(
            f"{qid:6s} "
            f"{metrics['overlap_pct']:>8.1f}% "
            f"{metrics['overlap_count']:>3d}/{metrics['base_count']:<1d} "
            f"{metrics['base_count']:>3d} "
            f"{metrics['curr_count']:>3d}  "
            f"{curr_q.get('category', '')[:20]:20s} "
            f"{status}"
        )

        if metrics["regression"]:
            regressions.append({
                "id": qid,
                "query": curr_q.get("query", ""),
                "lost": metrics["lost"],
                "gained": metrics["gained"],
            })

    # Summary
    overall_pct = round(total_overlap / max(total_base_docs, 1) * 100, 1)

    print(f"\n{'=' * 72}")
    print(f"  总重叠率: {overall_pct}% ({total_overlap}/{total_base_docs})")
    print(f"  回归项: {len(regressions)}/{len(all_ids)}")

    if regressions:
        print(f"\n{'🔴 回归详情':-^72}")
        for r in regressions:
            print(f"\n  [{r['id']}] {r['query'][:60]}")
            print(f"    丢失: {r['lost'][:5]}")
            print(f"    新增: {r['gained'][:5]}")
        print(f"\n  ❌ 建议: 检查改造是否影响了二通道检索质量")
        sys.exit(1)
    else:
        print(f"\n  ✅ 全部通过 —— 改造未影响现有检索质量\n")


if __name__ == "__main__":
    main()
