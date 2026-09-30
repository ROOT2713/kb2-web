"""check_cron_silence.py 单元测试（纯函数，零 IO、零 LLM）。

重点锁两件事：
  ① **正确行为**：当日 START/OK 到齐才静默，缺失/FAIL/日志丢失/未到窗口各态分明；
  ② **R7 提案的日期缺陷回归锚**：日志里若只有**旧日期**的心跳行（即使 job 名
     完全正确），也必须判为「今天沉默」——这是 R-P2-4 `_DATE_RE` 匹配任意日期
     导致「永不告警」的那条缺陷的锁。回退该锚定逻辑 ⇒ 本文件必须变红。
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_cron_silence.py"
)
_spec = importlib.util.spec_from_file_location("check_cron_silence", _SCRIPT)
assert _spec and _spec.loader, f"无法加载 {_SCRIPT}"
cs = importlib.util.module_from_spec(_spec)
# ★ 必须先把模块注册进 sys.modules 再 exec_module —— 否则目标模块里的
#   @dataclass 在解析注解时会 sys.modules.get(cls.__module__) 拿到 None，
#   报 "AttributeError: 'NoneType' object has no attribute '__dict__'"（收集期错）。
sys.modules[_spec.name] = cs
_spec.loader.exec_module(cs)

TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 6, 0, 0)          # 已过 0300/0400/0500 全部窗口
JOB = "cron_stale_detection"
PATH = "/tmp/fake_cron_stale.log"


def _call(text, **kw):
    return cs.check_silence(
        text, JOB, "0400", TODAY, NOW, kw.pop("grace", 90), PATH, **kw
    )


# ── ① 真实格式解析 ────────────────────────────────────────────
def test_real_f0_format_parsed():
    """F0 wrapper 的真实输出形态必须被解析（R7 的 _TS_PREFIX 漏 [HEARTBEAT] 段）。"""
    text = (
        "[2026-09-30 04:00:01] [HEARTBEAT] START cron_stale_detection "
        "interp=/home/ubuntu/.hermes/hermes-agent/venv/bin/python3\n"
        "[2026-09-30 04:00:02] [HEARTBEAT] OK cron_stale_detection rc=0\n"
    )
    hb = cs.parse_heartbeats(text)
    assert (2026, 9, 30) == (TODAY.year, TODAY.month, TODAY.day)
    assert ("2026-09-30", "START", JOB) in hb
    assert ("2026-09-30", "OK", JOB) in hb


def test_all_present_is_silent():
    text = (
        "[2026-09-30 04:00:01] [HEARTBEAT] START cron_stale_detection interp=/x\n"
        "[2026-09-30 04:00:02] [HEARTBEAT] OK cron_stale_detection rc=0\n"
    )
    assert _call(text) == []


# ── ② ★ R7 日期缺陷回归锚 ────────────────────────────────────
def test_stale_dated_lines_do_not_count_as_today():
    """只有 09-27 的心跳（job 名完全正确）⇒ 今天必须判沉默。

    R7 版 _DATE_RE 匹配任意 \\d{4}-\\d{2}-\\d{2} ⇒ 这里会误判为「今天已跑」
    ⇒ 永不告警。本用例是那条缺陷的锁。
    """
    text = (
        "[2026-09-27 04:00:01] [HEARTBEAT] START cron_stale_detection interp=/x\n"
        "[2026-09-27 04:00:02] [HEARTBEAT] OK cron_stale_detection rc=0\n"
    )
    probs = _call(text)
    assert probs, "旧日期心跳被当成了今天的心跳（R7 缺陷复发）"
    assert any("dated 2026-09-30" in p.reason for p in probs)


def test_today_only_missing_ok_still_counts_day_seen():
    """当日有 START 无 OK ⇒ 报 OK 缺失，且不得报「无当日心跳」。"""
    text = "[2026-09-30 04:00:01] [HEARTBEAT] START cron_stale_detection interp=/x\n"
    probs = _call(text)
    assert len(probs) == 1 and "missing OK" in probs[0].reason


# ── ③ 各异常态 ───────────────────────────────────────────────
def test_fail_tag_alerts():
    text = (
        "[2026-09-30 04:00:01] [HEARTBEAT] START cron_stale_detection interp=/x\n"
        "[2026-09-30 04:00:02] [HEARTBEAT] FAIL cron_stale_detection rc=1\n"
    )
    probs = _call(text)
    assert any("FAIL" in p.reason for p in probs)
    assert any("missing OK" in p.reason for p in probs)


def test_before_window_no_alert():
    """未到窗口（03:00 检查 04:00 的任务）⇒ 不告警。"""
    early = datetime(2026, 9, 30, 3, 0, 0)
    probs = cs.check_silence("", JOB, "0400", TODAY, early, 90, PATH)
    assert probs == []


def test_missing_log_alerts():
    probs = _call(None)
    assert probs and "heartbeat log missing" in probs[0].reason


def test_job_name_drift_alerts():
    """R7 的 EXPECTED_JOBS 写的是 'START confidence'（错误标记）⇒ 误报。

    这里从反面锁：日志里出现的是 R7 式短名 ⇒ 真实 job 名对不上 ⇒ 必须告警。
    """
    text = (
        "[2026-09-30 04:00:01] [HEARTBEAT] START confidence interp=/x\n"
        "[2026-09-30 04:00:02] [HEARTBEAT] OK confidence rc=0\n"
    )
    probs = _call(text)
    assert probs and any("dated 2026-09-30" in p.reason for p in probs)


def test_prose_line_not_treated_as_heartbeat():
    """正文里提到标记词、但无 [TS] [HEARTBEAT] 前缀 ⇒ 不算心跳。"""
    text = "运维笔记：我们讨论了 START cron_stale_detection 的设计，OK 与否看日志。\n"
    assert cs.parse_heartbeats(text) == []
    probs = _call(text)
    assert probs  # 无当日心跳 ⇒ 告警


@pytest.mark.parametrize("tag", ["START", "OK"])
def test_partial_tags(tag):
    text = f"[2026-09-30 04:00:01] [HEARTBEAT] {tag} cron_stale_detection interp=/x\n"
    probs = _call(text)
    assert probs, f"只有 {tag} 时不得静默"


# ── ④ [HEARTBEAT] 段是承重精度约束（不是装饰）────────────────────
def test_line_without_heartbeat_segment_ignored():
    """行首有时间戳、也带 START + 任务名，但中段不是 [HEARTBEAT] ⇒ 不算心跳。

    日志文件里还有 python 脚本自身的输出（可能形如 `[INFO] ...`），
    若无条件接受任意方括号段，这类行会被误认成心跳。本用例锁住该要求。
    """
    text = "[2026-09-30 04:00:01] [INFO] START cron_stale_detection interp=/x\n"
    assert cs.parse_heartbeats(text) == []
    assert _call(text)  # 无当日心跳 ⇒ 告警


# ── ⑤ ★ JOBS 表 ↔ 真实 wrapper 三向一致性（承重配置）──────────────
def test_jobs_table_matches_real_wrappers():
    """JOBS 表的 (时刻, job 名, 日志路径) 必须与真实 wrapper 逐字一致。

    R7 提案用的 `START confidence` 式短名与 wrapper 实际 `$JOB` 不符 ⇒
    永久误报。本用例把「标记漂移」变成可被测试抓到的错误：
    job 名改了、cron 时刻改了、日志路径改了，任一不同即红。
    """
    import re as _re

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    assert len(cs.JOBS) == 3, "治理任务应为三项"

    for hhmm, job, log_path in cs.JOBS:
        wrapper = scripts_dir / f"{job}.sh"
        assert wrapper.exists(), f"wrapper 不存在：{wrapper}"
        w = wrapper.read_text(encoding="utf-8")

        m_job = _re.search(r"^JOB=(\S+)", w, _re.MULTILINE)
        assert m_job, f"{wrapper.name} 未找到 JOB= 赋值"
        assert m_job.group(1) == job, f"job 名漂移：表={job} wrapper={m_job.group(1)}"

        assert log_path in w, f"日志路径漂移：表={log_path} 未出现在 {wrapper.name}"

        m_cron = _re.search(
            r"(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*\s+" + _re.escape(str(wrapper)),
            w,
        )
        assert m_cron, f"{wrapper.name} 未找到 crontab 定义行"
        # cron 字段序 = 分 时 日 月 周 ⇒ hhmm = 时 * 100 + 分
        minute, hour = int(m_cron.group(1)), int(m_cron.group(2))
        got = f"{hour:02d}{minute:02d}"
        assert got == hhmm, f"cron 时刻漂移：表={hhmm} wrapper={got}"

