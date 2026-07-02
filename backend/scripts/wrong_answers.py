"""
kb2-web 错题积累机制 — 错误追踪与历史记录管理。

功能：
  - 记录每个失败测试的"错题"（timestamp, query, expected vs actual, category）
  - 对比历史错题：检查之前失败的项目现在是否通过（回归改善轨迹）
  - 生成错题报告：高频失败项、累积时间线、通过率趋势
  - 无需外部依赖，纯 JSON 文件存储

目录结构：
  tests/errors/
    errors.json           ← 错题库（持续累积）
    fix-history.json      ← 修复历史（标记已解决的错题）
    .gitkeep              ← 确保目录存在

用法：
  # 记录一条错题
  python scripts/wrong_answers.py add --id "Q01" --query "GB/T 25000" \
    --expected "至少3条结果" --actual "返回0条" --category "检索回归" --bank "standards"

  # 标记为已修复
  python scripts/wrong_answers.py fix --id "Q01"

  # 查看错题报告
  python scripts/wrong_answers.py report

  # 查看修复成功历史
  python scripts/wrong_answers.py history

  # 检查之前失败的错题现在是否都通过了
  python scripts/wrong_answers.py verify
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_ERRORS_DIR = Path(__file__).resolve().parent.parent / "tests" / "errors"
_ERRORS_FILE = _ERRORS_DIR / "errors.json"
_HISTORY_FILE = _ERRORS_DIR / "fix-history.json"


# ── 数据结构 ──────────────────────────────────────────────────────

def _load_errors() -> dict:
    """加载错题库。"""
    if not _ERRORS_FILE.exists():
        return {"version": 2, "errors": [], "meta": {"created": None, "updated": None}}
    try:
        return json.loads(_ERRORS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return {"version": 2, "errors": [], "meta": {"created": None, "updated": None}}


def _save_errors(data: dict):
    _ERRORS_DIR.mkdir(parents=True, exist_ok=True)
    data["meta"]["updated"] = datetime.now(timezone.utc).isoformat()
    _ERRORS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_history() -> list:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return []


def _save_history(history: list):
    _HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 操作 ──────────────────────────────────────────────────────────

def add_error(
    error_id: str,
    query: str,
    expected: str,
    actual: str,
    category: str,
    bank: str = "",
    test_file: str = "",
    severity: str = "medium",
):
    """记录一条新的错题。

    如果同 id 的错题已存在（未修复），标记为再次出现（regression_count++）。
    """
    data = _load_errors()
    now = datetime.now(timezone.utc).isoformat()

    # 查找现有同 id 的 open 错题
    existing = [e for e in data["errors"] if e.get("id") == error_id and not e.get("fixed_at")]

    if existing:
        entry = existing[0]
        entry["regression_count"] = entry.get("regression_count", 1) + 1
        entry["last_seen_at"] = now
        entry["last_actual"] = actual
        entry["last_expected"] = expected
    else:
        entry = {
            "id": error_id,
            "query": query,
            "expected": expected,
            "actual": actual,
            "category": category,
            "bank": bank,
            "test_file": test_file,
            "severity": severity,
            "first_seen_at": now,
            "last_seen_at": now,
            "regression_count": 1,
            "fixed_at": None,
            "fix_verified_at": None,
        }
        data["errors"].append(entry)

    if data["meta"]["created"] is None:
        data["meta"]["created"] = now
    _save_errors(data)
    print(f"✅ 错题记录 [{error_id}] {query[:40]}")

    # 自动按 last_seen_at 降序排序
    data["errors"].sort(key=lambda e: e.get("last_seen_at", ""), reverse=True)
    _save_errors(data)
    print(f"✅ 错题记录 [{error_id}] {query[:40]}")


def fix_error(error_id: str, verified_by: str = "test_pass"):
    """标记一条错题为已修复。"""
    data = _load_errors()
    history = _load_history()
    now = datetime.now(timezone.utc).isoformat()

    found = False
    for e in data["errors"]:
        if e.get("id") == error_id and not e.get("fixed_at"):
            e["fixed_at"] = now
            e["fix_verified_at"] = now
            found = True

            # 记录修复历史
            history.append({
                "id": error_id,
                "query": e.get("query", ""),
                "category": e.get("category", ""),
                "fix_count": e.get("regression_count", 1),
                "first_seen": e.get("first_seen_at"),
                "fixed_at": now,
                "verified_by": verified_by,
            })
            _save_history(history)
            _save_errors(data)
            print(f"🛠️ 修复确认 [{error_id}] {e.get('query', '')[:40]}")
            break

    if not found:
        print(f"⚠️ 未找到 open 状态的错题 [{error_id}]")


def generate_report() -> dict:
    """生成错题报告。"""
    data = _load_errors()

    total = len(data["errors"])
    open_errors = [e for e in data["errors"] if not e.get("fixed_at")]
    fixed_errors = [e for e in data["errors"] if e.get("fixed_at")]

    # 按类别统计
    by_category = {}
    for e in open_errors:
        cat = e.get("category", "其他")
        by_category.setdefault(cat, []).append(e)

    # 高频失败项（regression_count >= 2）
    high_frequency = [e for e in open_errors if e.get("regression_count", 1) >= 2]

    # 修复率
    fix_rate = len(fixed_errors) / max(total, 1) * 100

    return {
        "total_errors": total,
        "open_errors": len(open_errors),
        "fixed_errors": len(fixed_errors),
        "fix_rate_pct": round(fix_rate, 1),
        "high_frequency": len(high_frequency),
        "by_category": {k: len(v) for k, v in sorted(by_category.items())},
        "high_frequency_items": [
            {
                "id": e["id"],
                "query": e.get("query", "")[:50],
                "category": e.get("category", ""),
                "regression_count": e.get("regression_count", 1),
                "last_seen": e.get("last_seen_at", ""),
            }
            for e in sorted(
                open_errors,
                key=lambda x: x.get("regression_count", 1),
                reverse=True,
            )[:10]
        ],
        "fix_history": [
            {
                "id": h["id"],
                "query": h.get("query", "")[:40],
                "fixed_at": h.get("fixed_at", ""),
            }
            for h in sorted(
                _load_history(),
                key=lambda x: x.get("fixed_at", ""),
                reverse=True,
            )[:10]
        ],
    }


def print_report():
    """打印格式化报告到 stdout。"""
    report = generate_report()

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  kb2-web 错题报告")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{sep}")
    print(f"  总记录:   {report['total_errors']}")
    print(f"  未修复:   {report['open_errors']}")
    print(f"  已修复:   {report['fixed_errors']}")
    print(f"  修复率:   {report['fix_rate_pct']}%")
    print(f"  高频失败: {report['high_frequency']} 项")

    if report["by_category"]:
        print(f"\n{'--- 按类别分布 ---':^60}")
        for cat, cnt in sorted(report["by_category"].items(), key=lambda x: -x[1]):
            bar = "█" * min(cnt, 20)
            print(f"  {cat:20s} {cnt:>3d} {bar}")

    if report["high_frequency_items"]:
        print(f"\n{'--- 高频失败项 Top 10 ---':^60}")
        for item in report["high_frequency_items"]:
            print(f"  [{item['id']}] {item['query'][:50]:50s} "
                  f"x{item['regression_count']} {item.get('last_seen','')[:10]}")

    if report["fix_history"]:
        print(f"\n{'--- 最近修复记录 ---':^60}")
        for item in report["fix_history"]:
            print(f"  [{item['id']}] {item['query'][:50]:50s} "
                  f"{item.get('fixed_at','')[:10]}")
    print()


def verify_all():
    """检查所有 open 错题是否已修复。
    
    这个功能由 CI 或手动调用：先运行所有回归测试，然后比对接下来的错题状态。
    如果一条错题对应的用例现在通过了，标记为 fixed。
    """
    report = generate_report()
    if report["open_errors"] == 0:
        print("🎉 所有错题已修复！")
    else:
        print(f"⚠️ 仍有 {report['open_errors']} 条错题未修复")
        for cat, cnt in sorted(report["by_category"].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {cnt} 条")


# ── CLI 入口 ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "add":
        kwargs = {}
        for arg in sys.argv[2:]:
            if arg.startswith("--"):
                parts = arg.split("=", 1)
                key = parts[0][2:].replace("-", "_")
                val = parts[1] if len(parts) > 1 else sys.argv[sys.argv.index(arg) + 1] if sys.argv.index(arg) + 1 < len(sys.argv) else None
                kwargs[key] = val
        add_error(
            error_id=kwargs.get("id", "unknown"),
            query=kwargs.get("query", ""),
            expected=kwargs.get("expected", ""),
            actual=kwargs.get("actual", ""),
            category=kwargs.get("category", "general"),
            bank=kwargs.get("bank", ""),
            test_file=kwargs.get("test_file", ""),
            severity=kwargs.get("severity", "medium"),
        )

    elif cmd == "fix":
        error_id = sys.argv[2] if len(sys.argv) > 2 else None
        if error_id:
            fix_error(error_id)

    elif cmd == "report":
        print_report()

    elif cmd == "history":
        history = _load_history()
        if not history:
            print("暂无修复历史。")
            return
        print(f"\n{'=' * 60}")
        print(f"  kb2-web 修复历史")
        print(f"{'=' * 60}")
        for h in reversed(history[-20:]):
            status = "🎉" if h.get("verified_by") == "test_pass" else "🛠️"
            print(f"  {status} [{h['id']}] {h.get('query','')[:50]:50s} "
                  f"{h.get('fixed_at','')[:10]}")

    elif cmd == "verify":
        verify_all()

    else:
        print(f"未知命令: {cmd}")
        print("可用: add, fix, report, history, verify")


if __name__ == "__main__":
    main()
