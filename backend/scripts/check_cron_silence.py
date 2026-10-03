#!/usr/bin/env python3
"""治理 cron「报沉默」看门狗 —— 心跳行缺失检测（只读，零副作用）。

┌─ 为什么需要它 ────────────────────────────────────────────────────┐
│ N1：治理 cron（confidence 重算 / upload cleanup 两项）             │
│ 曾连续失效 87 天无人知晓（rc≠0 被 >> log 吞掉）。                  │
│ F0（6745f6a）已给三个 wrapper 加 [HEARTBEAT] START/OK 行，但         │
│ **没有任何消费方**（心跳只写不读）⇒ 若 cron 被删 / systemd 停摆 /   │
│ 日志被轮转替换，连 FAIL 都不会有 —— N1 只解决了一半。              │
│ 本脚本补上「读」的一端：到点检查**当日**心跳行是否存在，缺失即告警。 │
└──────────────────────────────────────────────────────────────────┘

输出策略（watchdog 模式）：全部到齐 → stdout 为空（定时任务静默）；
存在缺失 → 输出告警文本。这样「正常」不产生周期性噪音。

与 R7 提案（R-P2-4 silence_watchdog）的关系 —— 该提案实测**不可采用**，
本实现是其修正版，四处差异（均有复现证据，见 tests/unit/test_cron_silence.py）：
  ① [P1] R-P2-4 的 `_DATE_RE = r"\\d{4}-\\d{2}-\\d{2}"` 匹配**任意**日期，
     且 `today` 变量算出后未参与过滤 ⇒ 日志里只要有**任何一天**的心跳，
     就认定今天也跑了 ⇒ **永不告警**。本实现锚定「行首时间戳日期 == 今天」。
  ② [P1] R-P2-4 的 EXPECTED_JOBS 写 `"START confidence"`，而 F0 wrapper 实际
     输出 `"START cron_confidence_recalc"` ⇒ 标记漂移 ⇒ 永久误报。
  ③ [P1] R-P2-4 的 `_TS_PREFIX` 不吞 `[HEARTBEAT]` 段 ⇒ 真实行
     `[TS] [HEARTBEAT] START x` 判不出心跳 ⇒ 永久误报。
  ④ [P2] R-P2-4 假定单一日志 `/var/log/kb2-gov/gov-cron.log`；实际是
     `~/kb2-web/logs/` 下**两份**独立日志（该目录不存在 ⇒ 首步即崩）。
     注：2026-10-01 前为三份；stale 检测停用后同步收紧为两份。

用法：
    python3 check_cron_silence.py                 # 检查全部配置项
    python3 check_cron_silence.py --grace 30      # 覆盖宽限窗（分钟）
    python3 check_cron_silence.py --dry-run       # 打印匹配详情，不判失败
    python3 check_cron_silence.py --today 2026-09-30   # 回放指定日期（测试用）
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# ── 治理任务：预期触发时刻 / 真实 job 名 / 真实日志路径 ─────────────
# job 名必须与 wrapper 实际输出逐字一致（F0 cron_*.sh 的 $JOB）。
# 任何一处不一致 ⇒ 立即误报，因此本表是承重点，改动必须同步跑测试。
#
# ★ 2026-10-02：cron_stale_detection 已从本表**移除**。
#   该任务 2026-10-01 停用（crontab 行已注释，改人工触发），但看门狗仍
#   把它当「预期每日心跳」⇒ 每天 06:40 等不到 ⇒ 连续两日误报
#   「cron 可能整体死亡」（实测 cron_stale.log 末条为 10-01 04:00）。
#   铁律：任务停用/恢复时，本表必须与 crontab 同步改 —— 否则留下
#   「永久误报」或「静默漏报」两类哑弹。
#   防复发：tests/unit/test_cron_silence.py
#   ::test_jobs_table_excludes_disabled_crontab_entries
JOBS: list[tuple[str, str, str]] = [
    ("0300", "cron_confidence_recalc", "/home/ubuntu/kb2-web/logs/cron_confidence.log"),
    ("0500", "cron_upload_cleanup", "/home/ubuntu/kb2-web/logs/cron_upload_cleanup.log"),
]

# 真实心跳行形态（F0 wrapper 的 hb() 输出）：
#   [2026-09-30 03:00:01] [HEARTBEAT] START cron_confidence_recalc interp=/venv/bin/python3
#   [2026-09-30 03:09:56] [HEARTBEAT] OK cron_confidence_recalc rc=0
_HB_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2})(?:[ T][\d:.]+)?\]\s*"   # 行首时间戳
    r"\[HEARTBEAT\]\s*"                                      # 固定段
    r"(?P<tag>START|OK|FAIL)\s+"                             # 心跳标签
    r"(?P<job>\S+)"                                          # 任务名
)

WINDOW_GRACE_DEFAULT = 90  # 分钟：三个任务实测 1-10 分钟完成，90 分钟远够


@dataclass
class Problem:
    job: str
    reason: str

    def __str__(self) -> str:
        return f"{self.job}: {self.reason}"


def parse_heartbeats(text: str) -> list[tuple[str, str, str]]:
    """解析心跳行 → [(日期, 标签, 任务名)]。非心跳行忽略。"""
    out = []
    for line in (text or "").splitlines():
        m = _HB_RE.match(line.strip())
        if m:
            out.append((m.group("ts"), m.group("tag"), m.group("job")))
    return out


def check_silence(
    log_text: str | None,
    job: str,
    expect_hhmm: str,
    today: date,
    now: datetime,
    grace_minutes: int = WINDOW_GRACE_DEFAULT,
    log_path: str = "",
) -> list[Problem]:
    """返回该任务的心跳缺失清单（空 = 未沉默）。

    log_text=None 表示日志文件不存在/不可读。
    未到检测窗口（now < 预期时刻 + grace）→ 返回空（不告警，由下次调度覆盖）。
    """
    hh, mm = int(expect_hhmm[:2]), int(expect_hhmm[2:])
    deadline = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(
        minutes=grace_minutes
    )
    if now < deadline:
        return []  # 未到窗口，不算沉默

    if log_text is None:
        return [Problem(job, f"heartbeat log missing: {log_path}")]

    iso_today = today.isoformat()
    seen = {
        tag
        for (d, tag, j) in parse_heartbeats(log_text)
        if d == iso_today and j == job          # ★ 日期锚定「今天」+ 任务名一致
    }
    if not seen:
        return [
            Problem(
                job,
                f"no heartbeat lines for {job} dated {iso_today} in {log_path}"
                "（cron 可能整体死亡 / 日志被轮转 / 格式未覆盖）",
            )
        ]

    problems = []
    if "START" not in seen:
        problems.append(Problem(job, f"missing START heartbeat (expect {expect_hhmm})"))
    if "OK" not in seen:
        problems.append(Problem(job, f"missing OK heartbeat (expect {expect_hhmm})"))
    if "FAIL" in seen:
        problems.append(Problem(job, f"FAIL heartbeat present (expect {expect_hhmm})"))
    return problems


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="silence watchdog for kb2 gov cron")
    ap.add_argument("--grace", type=int, default=WINDOW_GRACE_DEFAULT,
                    help="预期触发时刻后的宽限分钟数")
    ap.add_argument("--dry-run", action="store_true", help="打印匹配详情，不判失败")
    ap.add_argument("--today", help="覆盖『今天』（YYYY-MM-DD，回放用）")
    args = ap.parse_args()

    now = datetime.now()
    today = date.fromisoformat(args.today) if args.today else now.date()

    all_problems: list[Problem] = []
    detail: list[str] = []
    for hhmm, job, path in JOBS:
        text = _read(path)
        probs = check_silence(text, job, hhmm, today, now, args.grace, path)
        all_problems.extend(probs)
        hb = parse_heartbeats(text or "")
        todays = [h for h in hb if h[0] == today.isoformat()]
        detail.append(
            f"  {hhmm} {job:<26} 日志={'OK' if text is not None else '缺失'} "
            f"心跳行={len(hb)} 当日行={len(todays)} 缺失={len(probs)}"
        )

    if args.dry_run:
        print(f"DRY-RUN today={today.isoformat()} grace={args.grace}min")
        print("\n".join(detail))
        if all_problems:
            print("problems:")
            for p in all_problems:
                print(f"  ALERT {p}")
        return 0

    if not all_problems:
        return 0  # 全部到齐 → 静默（watchdog 语义）

    print(f"🚨 治理 cron「报沉默」告警 {now.strftime('%Y-%m-%d %H:%M')}")
    for p in all_problems:
        print(f"   ALERT {p}")
    print("\n排查：journalctl / 查看 ~/kb2-web/logs/*.log 的 HEARTBEAT 行；"
          "任务 crontab 定义见 crontab -l（0 3/5 * * *；stale 检测 2026-10-01 已停用）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
