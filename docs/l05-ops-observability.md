# L05 运维观测实施方案 — kb2-web v2

> 项目: kb2-web | 服务端口: 3027 (kb2-web), 8888 (Hindsight)  
> DB: `/home/ubuntu/kb-web/data/kb.db` | 后端: FastAPI (uvicorn, single worker)  
> 系统: Linux (systemd) | 发布日期: 2026-07-09

---

## 目录

1. [现状分析](#1-现状分析)
2. [整体架构](#2-整体架构)
3. [健康检查方案](#3-健康检查方案)
4. [查询指标采集方案](#4-查询指标采集方案)
5. [日报生成方案](#5-日报生成方案)
6. [告警阈值与通知](#6-告警阈值与通知)
7. [交付物清单](#7-交付物清单)
8. [工时估计](#8-工时估计)
9. [附录：SQL 查询 & 脚本参考](#9-附录sql-查询--脚本参考)

---

## 1. 现状分析

### 1.1 现有基础设施

| 项目 | 状态 | 说明 |
|------|------|------|
| `/health` 端点 (kb2-web) | ✅ 可用 | 返回 `{"status":"ok","version":"2.0.0"}`，无需认证 |
| `/api/admin/health` 端点 | ✅ 可用 | 含 DB 连接 + Hindsight 连通性检查 |
| Hindsight `/health` | ✅ 可用 | 返回 `{"status":"healthy","database":"connected"}` |
| systemd 服务 | ✅ 已配 | `kb2-web.service` (3027), `kb-web.service` (旧版) |
| 审计日志 (audit_log 表) | ✅ 已存在 | 含 user_id, query, tokens_used, response_ms, rejected, created_at |
| 主动监控 | ❌ 无 | 仅手动 curl 检查 |
| 集中式日志收集 | ❌ 无 | 仅 stdout |
| 告警通知 | ❌ 无 | 无 |
| 日报生成 | ❌ 无 | 无 |

### 1.2 audit_log 表结构（核心指标数据源）

```sql
CREATE TABLE audit_log (
    id            INTEGER   PRIMARY KEY AUTOINCREMENT,
    user_id       VARCHAR(64) NOT NULL,     -- 查询用户
    query         VARCHAR(500) NOT NULL,     -- 查询内容
    answer        TEXT,                      -- 回答内容
    sources       TEXT,                      -- 来源 JSON
    tokens_used   INTEGER    DEFAULT 0,      -- 消耗 token 数
    cache_hit     INTEGER    DEFAULT 0,      -- 0=未命中, 1=精确命中, 2=语义命中
    response_ms   INTEGER    DEFAULT 0,      -- 响应耗时 (毫秒)
    rejected      VARCHAR(32),               -- NULL=已应答, 其他=拒答原因
    created_at    DATETIME   DEFAULT (datetime('now')),
    INDEX ix_audit_log_created_at (created_at),
    INDEX ix_audit_log_user_id (user_id)
);
```

> **关键字段**：`response_ms` 用于延迟分析, `rejected` 用于拒答率, `cache_hit` 用于缓存命中率, `created_at` 用于时间窗口过滤。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        cron (每5分钟 / 每日)                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │ Health Check       │    │ Metric Collector  │    │ Daily Report │  │
│  │ (每5分钟)           │    │ (每5分钟聚合)      │    │ (每日 08:00) │  │
│  └────────┬──────────┘    └────────┬─────────┘    └──────┬───────┘  │
│           │                        │                     │          │
│           ▼                        ▼                     ▼          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    日志 / 通知层                                │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │  │
│  │  │ kb2-web/logs │  │ Terminal    │  │ (未来: Slack/邮件)    │ │  │
│  │  │  (本地文件)     │  │ stdout      │  │                      │ │  │
│  │  └─────────────┘  └──────────────┘  └──────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 健康检查方案

### 3.1 方案选择

**选型：systemd `ExecStartPre` + 外部 cron 检查双重机制**  
理由：已有 systemd 管理，无需额外部署成本；cron 可提供更丰富的健康状态日志和自愈。

### 3.2 systemd 自动重启（已有）

`kb2-web.service` 已配置 Restart=on-failure。确认/增强配置：

```ini
[Unit]
Description=kb2-web v2
After=network.target hindsight.service

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/kb2-web/backend
ExecStart=/home/ubuntu/kb2-web/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3027
Restart=on-failure
RestartSec=10
User=ubuntu
Environment=PYTHONPATH=/home/ubuntu/kb2-web/backend

[Install]
WantedBy=multi-user.target
```

> systemd 负责进程级守护；Restart=on-failure 在进程崩溃时自动拉起。

### 3.3 外部健康检查脚本（新增）

**文件**：`backend/scripts/health_check.sh`

功能：
1. 检查 kb2-web `/health` 端点 (127.0.0.1:3027)
2. 检查 Hindsight `/health` 端点 (127.0.0.1:8888)
3. 检查 DB 连通性（通过 kb2-web `/api/admin/health` 端点）
4. 服务挂掉时自动 systemctl restart
5. 持续失败时写报警文件到日志

```bash
#!/usr/bin/env bash
# ── Health check: kb2-web + Hindsight + DB ──
# Runs every 5 minutes via cron.
#
# Install:
#   */5 * * * * /home/ubuntu/kb2-web/backend/scripts/health_check.sh >> /home/ubuntu/kb2-web/logs/health.log 2>&1

set -euo pipefail

BASE=/home/ubuntu/kb2-web
LOG_DIR=$BASE/logs
mkdir -p "$LOG_DIR"

NOW=$(date '+%Y-%m-%d %H:%M:%S')
FAILURES=0
ALERT_FILE="$LOG_DIR/.health_alert"

# ── Check kb2-web ──
if curl -sf http://127.0.0.1:3027/health > /dev/null 2>&1; then
    echo "$NOW [OK] kb2-web: /health reachable"
else
    echo "$NOW [FAIL] kb2-web: /health unreachable → restarting"
    sudo systemctl restart kb2-web.service
    FAILURES=$((FAILURES + 1))
fi

# ── Check Hindsight ──
if curl -sf http://127.0.0.1:8888/health > /dev/null 2>&1; then
    echo "$NOW [OK] Hindsight: /health reachable"
else
    echo "$NOW [FAIL] Hindsight: /health unreachable"
    FAILURES=$((FAILURES + 1))
fi

# ── Check kb2-web detailed health (DB) ──
DETAILED=$(curl -sf http://127.0.0.1:3027/api/admin/health 2>&1) || true
if echo "$DETAILED" | grep -q '"db":"ok"'; then
    echo "$NOW [OK] DB: connected"
else
    echo "$NOW [FAIL] DB: $(echo $DETAILED | grep -oP '"db":"[^"]*"' || echo 'unknown')"
    FAILURES=$((FAILURES + 1))
fi

# ── Alert file management ──
if [ "$FAILURES" -ge 2 ]; then
    # Two or more failures → write alert
    echo "$NOW CRITICAL: $FAILURES services failed" > "$ALERT_FILE"
    echo "$NOW [ALERT] $FAILURES checks failed (threshold ≥ 2)"
else
    # Clear alert when healthy
    if [ -f "$ALERT_FILE" ]; then
        echo "$NOW [RECOVER] All services healthy again" | tee >(cat >> "$ALERT_FILE")
        rm -f "$ALERT_FILE"
    fi
fi
```

### 3.4 健康检查执行计划

| 执行方式 | 频率 | 检查项 | 失败动作 |
|----------|------|--------|----------|
| systemd | 即时 | 进程存活 | `Restart=on-failure` 自动拉起 |
| cron (`health_check.sh`) | 每 5 分钟 | kb2-web /health | systemctl restart |
| cron (`health_check.sh`) | 每 5 分钟 | Hindsight /health | 写日志告警 |
| cron (`health_check.sh`) | 每 5 分钟 | DB 连通性 | 写日志告警 |

### 3.5 自愈策略

| 故障场景 | 恢复手段 | 预期恢复时间 |
|----------|----------|-------------|
| kb2-web 进程 OOM | systemd `Restart=on-failure` | ≤15s |
| kb2-web 无响应(stuck) | cron 检测 → systemctl restart | ≤30s |
| Hindsight 挂掉 | cron 检测 → 写告警文件 | 人工介入 |
| DB 损坏 | cron 检测 → 写告警文件 | 人工修复 |
| 内存泄漏 | 3 次重启仍失败 → 不再自动重启 | 人工介入 |

---

## 4. 查询指标采集方案

### 4.1 指标定义（基于 audit_log 表）

| 指标名称 | 计算公式 | 数据源 | 用途 |
|----------|----------|--------|------|
| 总查询次数 | `COUNT(*)` | audit_log | 系统负载 |
| 独立用户数 | `COUNT(DISTINCT user_id)` | audit_log | 用户活跃度 |
| 平均响应延迟(ms) | `AVG(response_ms)` | audit_log | 性能基准 |
| P50/P95/P99 延迟 | percentile | audit_log | 长尾延迟 |
| 拒答率 | `COUNT(rejected)/COUNT(*)` | audit_log | 质量监控 |
| 缓存命中率 | `SUM(cache_hit>0)/COUNT(*)` | audit_log | 缓存效率 |
| Token 消耗 | `SUM(tokens_used)` | audit_log | LLM 成本 |
| 拒答类型分布 | `rejected` 分组计数 | audit_log | 拒答原因分析 |
| 按小时查询分布 | 按 `created_at` 分组 | audit_log | 高峰时段 |
| Top-N 高频用户 | 按 user_id 分组排序 | audit_log | 用户画像 |
| Top-N 高频查询 | 按 query 分组排序 | audit_log | 热门查询 |

### 4.2 指标采集脚本

**文件**：`backend/scripts/collect_metrics.py`

```python
#!/usr/bin/env python3
"""查询指标采集 — 从 audit_log 表每日聚合。

输出: /home/ubuntu/kb2-web/logs/metrics/<YYYY-MM-DD>.json

配合 cron 每 5 分钟写入增量数据，日报从中读取。
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径 ──
BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

DB_PATH = os.environ.get("KB_DB_PATH", "/home/ubuntu/kb-web/data/kb.db")

# ── SQLite raw 连接（避免启动 FastAPI）──
import sqlite3
from collections import defaultdict


def get_connection():
    return sqlite3.connect(DB_PATH)


def collect_hourly_stats(conn, date_str: str):
    """按小时聚合指标。"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            strftime('%H', created_at) AS hour,
            COUNT(*)                                           AS total_queries,
            COUNT(DISTINCT user_id)                            AS unique_users,
            ROUND(AVG(CAST(response_ms AS REAL)), 1)           AS avg_latency_ms,
            ROUND(AVG(CASE WHEN response_ms > 0 THEN CAST(response_ms AS REAL) END), 1) AS avg_latency_ms_nonzero,
            SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected_count,
            SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END)        AS cache_hit_count,
            SUM(COALESCE(tokens_used, 0))                      AS total_tokens
        FROM audit_log
        WHERE date(created_at) = ?
        GROUP BY hour
        ORDER BY hour
    """, (date_str,))
    rows = cursor.fetchall()

    hourly = []
    for r in rows:
        hourly.append({
            "hour": r[0],
            "total_queries": r[1],
            "unique_users": r[2],
            "avg_latency_ms": r[3],
            "avg_latency_ms_nonzero": r[4],
            "rejected_count": r[5],
            "cache_hit_count": r[6],
            "total_tokens": r[7],
        })
    return hourly


def collect_totals(conn, date_str: str):
    """全天汇总指标。"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*)                                           AS total_queries,
            COUNT(DISTINCT user_id)                            AS unique_users,
            ROUND(AVG(CAST(response_ms AS REAL)), 1)           AS avg_latency_ms,
            ROUND(AVG(CASE WHEN response_ms > 0 THEN CAST(response_ms AS REAL) END), 1) AS avg_latency_ms_nonzero,
            SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected_count,
            SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END)        AS cache_hit_count,
            SUM(COALESCE(tokens_used, 0))                      AS total_tokens
        FROM audit_log
        WHERE date(created_at) = ?
    """, (date_str,))
    r = cursor.fetchone()

    # 百分位延迟
    cursor.execute("""
        SELECT response_ms FROM audit_log
        WHERE date(created_at) = ? AND response_ms > 0
        ORDER BY response_ms
    """, (date_str,))
    latencies = [row[0] for row in cursor.fetchall()]

    percentiles = {}
    if latencies:
        n = len(latencies)
        percentiles = {
            "p50": latencies[n // 2],
            "p90": latencies[int(n * 0.9)],
            "p95": latencies[int(n * 0.95)],
            "p99": latencies[int(n * 0.99)],
        }

    return {
        "date": date_str,
        "total_queries": r[0],
        "unique_users": r[1],
        "avg_latency_ms": r[2],
        "avg_latency_ms_nonzero": r[3],
        "rejected_count": r[4],
        "rejected_rate": round(r[4] / r[0] * 100, 2) if r[0] > 0 else 0,
        "cache_hit_count": r[5],
        "cache_hit_rate": round(r[5] / r[0] * 100, 2) if r[0] > 0 else 0,
        "total_tokens": r[6],
        "percentiles": percentiles,
        "hourly": collect_hourly_stats(conn, date_str),
    }


def collect_top_users(conn, date_str: str, limit: int = 10):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, COUNT(*) AS cnt
        FROM audit_log
        WHERE date(created_at) = ?
        GROUP BY user_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (date_str, limit))
    return [{"user_id": r[0], "query_count": r[1]} for r in cursor.fetchall()]


def collect_top_queries(conn, date_str: str, limit: int = 10):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT query, COUNT(*) AS cnt
        FROM audit_log
        WHERE date(created_at) = ?
        GROUP BY query
        ORDER BY cnt DESC
        LIMIT ?
    """, (date_str, limit))
    return [{"query": r[0], "count": r[1]} for r in cursor.fetchall()]


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_connection()
    try:
        result = collect_totals(conn, date_str)
        result["top_users"] = collect_top_users(conn, date_str)
        result["top_queries"] = collect_top_queries(conn, date_str)

        # 写入文件
        out_dir = BASE / "logs" / "metrics"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"[OK] 指标已写入 {out_path}")
        print(f"     查询: {result['total_queries']}, 用户: {result['unique_users']}, "
              f"平均延迟: {result['avg_latency_ms']}ms, "
              f"拒答率: {result['rejected_rate']}%, "
              f"缓存命中率: {result['cache_hit_rate']}%")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

### 4.3 增量采集模式（可选优化）

如需每 5 分钟采集，可扩展脚本记录 `last_id`：

```
# 持久化 last_id：
echo "LAST_ID=12345" > /home/ubuntu/kb2-web/logs/metrics/.cursor
# 下次只查 id > 12345 的记录
```

增量模式适合 Dashboard 实时刷新；首期建议只做每日聚合。

---

## 5. 日报生成方案

### 5.1 脚本设计

**文件**：`backend/scripts/daily_report.py`

```python
#!/usr/bin/env python3
"""日报生成 — 从 metrics JSON 生成 Markdown 报告。

输出: /home/ubuntu/kb2-web/logs/reports/<YYYY-MM-DD>.md
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/


def load_metrics(date_str: str) -> dict | None:
    path = BASE / "logs" / "metrics" / f"{date_str}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms/1000:.2f}s"
    return f"{ms:.0f}ms"


def generate_report(metrics: dict) -> str:
    d = metrics
    lines = []

    lines.append(f"# kb2-web 运维日报 — {d['date']}")
    lines.append(f"")
    lines.append(f"> 生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"")
    lines.append(f"## 总体概况")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 总查询次数 | {d['total_queries']} |")
    lines.append(f"| 独立用户数 | {d['unique_users']} |")
    lines.append(f"| 平均延迟 (含 0) | {fmt_ms(d['avg_latency_ms'])} |")
    lines.append(f"| 平均延迟 (仅非零) | {fmt_ms(d['avg_latency_ms_nonzero'])} |")
    lines.append(f"| 拒答数 / 拒答率 | {d['rejected_count']} / {d['rejected_rate']}% |")
    lines.append(f"| 缓存命中 / 命中率 | {d['cache_hit_count']} / {d['cache_hit_rate']}% |")
    lines.append(f"| Token 消耗 | {d['total_tokens']:,} |")
    lines.append(f"")

    # 百分位延迟
    p = d.get("percentiles", {})
    if p:
        lines.append(f"## 延迟百分位")
        lines.append(f"")
        lines.append(f"| 百分位 | 延迟 |")
        lines.append(f"|--------|------|")
        lines.append(f"| P50 | {fmt_ms(p.get('p50', 0))} |")
        lines.append(f"| P90 | {fmt_ms(p.get('p90', 0))} |")
        lines.append(f"| P95 | {fmt_ms(p.get('p95', 0))} |")
        lines.append(f"| P99 | {fmt_ms(p.get('p99', 0))} |")
        lines.append(f"")

    # 告警标记
    alerts = []
    if d["rejected_rate"] > 5:
        alerts.append(f"⚠️ **拒答率 {d['rejected_rate']}% 超过阈值 5%**")
    if p and p.get("p95", 0) > 60000:
        alerts.append(f"⚠️ **P95 延迟 {fmt_ms(p['p95'])} 超过阈值 60s**")
    if p and p.get("p99", 0) > 120000:
        alerts.append(f"🔴 **P99 延迟 {fmt_ms(p['p99'])} 超过严重阈值 120s**")
    if d["total_queries"] == 0:
        alerts.append(f"🔴 **当日无查询 — 服务可能异常**")
    if alerts:
        lines.append(f"## ⚠️ 告警汇总")
        lines.append(f"")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append(f"")

    # 按小时分布
    hourly = d.get("hourly", [])
    if hourly:
        lines.append(f"## 小时级查询分布")
        lines.append(f"")
        lines.append(f"| 小时 | 查询数 | 用户数 | 平均延迟 | 拒答数 | 缓存命中 | Token |")
        lines.append(f"|------|--------|--------|----------|--------|----------|-------|")
        for h in hourly:
            lines.append(
                f"| {h['hour']}:00 | {h['total_queries']} | {h['unique_users']} "
                f"| {fmt_ms(h['avg_latency_ms'])} | {h['rejected_count']} "
                f"| {h['cache_hit_count']} | {h['total_tokens']:,} |"
            )
        lines.append(f"")

    # Top 用户
    top_users = d.get("top_users", [])
    if top_users:
        lines.append(f"## Top 活跃用户")
        lines.append(f"")
        lines.append(f"| 排名 | 用户 | 查询次数 |")
        lines.append(f"|------|------|----------|")
        for i, u in enumerate(top_users, 1):
            lines.append(f"| {i} | {u['user_id']} | {u['query_count']} |")
        lines.append(f"")

    # Top 查询
    top_q = d.get("top_queries", [])
    if top_q:
        lines.append(f"## Top 高频查询")
        lines.append(f"")
        lines.append(f"| 排名 | 查询内容 | 次数 |")
        lines.append(f"|------|----------|------|")
        for i, q in enumerate(top_q, 1):
            truncated = q["query"][:60] + ("..." if len(q["query"]) > 60 else "")
            lines.append(f"| {i} | `{truncated}` | {q['count']} |")
        lines.append(f"")

    return "\n".join(lines)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    metrics = load_metrics(date_str)
    if metrics is None:
        print(f"[WARN] {date_str} 的指标数据不存在。请先运行 collect_metrics.py {date_str}")
        sys.exit(1)

    report = generate_report(metrics)

    out_dir = BASE / "logs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[OK] 日报已写入 {out_path}")
    print(report[:500] + "\n...")


if __name__ == "__main__":
    main()
```

### 5.2 日报示例输出

> **注**：以下为格式示例，首日运行后实际数据取决于 audit_log 表内容。

```markdown
# kb2-web 运维日报 — 2026-07-08

> 生成时间: 2026-07-09 00:05:00 UTC

## 总体概况

| 指标 | 数值 |
|------|------|
| 总查询次数 | 1,247 |
| 独立用户数 | 23 |
| 平均延迟 | 3.2s |
| 拒答率 | 2.8% |
| 缓存命中率 | 41.5% |
| Token 消耗 | 891,234 |

## 延迟百分位

| 百分位 | 延迟 |
|--------|------|
| P50 | 1.8s |
| P90 | 8.5s |
| P95 | 15.2s |
| P99 | 42.1s |

## 小时级查询分布
...

## 告警汇总
- ⚠️ P99 延迟 42.1s 接近阈值 60s
```

### 5.3 cron 定时执行

```bash
# crontab -e 添加以下条目：

# ── 每 5 分钟健康检查 ──
*/5 * * * * /home/ubuntu/kb2-web/backend/scripts/health_check.sh >> /home/ubuntu/kb2-web/logs/health.log 2>&1

# ── 每日 00:05 采集前一日指标 ──
5 0 * * * /home/ubuntu/kb2-web/backend/scripts/cron_collect_metrics.sh >> /home/ubuntu/kb2-web/logs/cron_metrics.log 2>&1

# ── 每日 00:10 生成前一日日报 ──
10 0 * * * /home/ubuntu/kb2-web/backend/scripts/cron_daily_report.sh >> /home/ubuntu/kb2-web/logs/cron_report.log 2>&1
```

---

## 6. 告警阈值与通知

### 6.1 阈值定义

| 指标 | 正常 | 警告 (WARN) | 严重 (CRITICAL) | 依据 |
|------|------|-------------|-----------------|------|
| 查询平均延迟 | < 10s | 10s–30s | > 30s | LLM 推理典型时间 |
| P95 延迟 | < 30s | 30s–60s | > 60s (任务要求) | L05 要求 >60s 告警 |
| P99 延迟 | < 60s | 60s–120s | > 120s | 长尾容忍度 |
| 拒答率 (rejected) | < 3% | 3%–5% | > 5% (任务要求) | L05 要求 >5% 告警 |
| 缓存命中率 | > 30% | 15%–30% | < 15% | 缓存效率 |
| 每小时无查询 | - | - | 连续 2 小时 0 查询 | 服务异常信号 |
| kb2-web 服务状态 | 运行 | - | 不健康 / 不可达 | 进程级 |
| Hindsight 状态 | 健康 | - | 不可达 | 依赖服务 |
| DB 连通性 | 正常 | - | 异常 | 数据层 |
| 内存使用 | < 70% | 70%–85% | > 85% | OOM 防范 |
| 磁盘使用 | < 80% | 80%–90% | > 90% | 日志/DB 空间 |

### 6.2 告警通知方式

**第一期（无外部通知基础设施）：**

| 级别 | 通知方式 | 内容 |
|------|----------|------|
| WARN | 日报标注 | 日报中「告警汇总」章节 |
| CRITICAL | 日报标注 + 写入 `logs/.health_alert` | 日报 + 健康检查输出加 [ALERT] 标记 |
| 服务重启 | 写入 `logs/health.log` | systemd 或 cron 触发重启时记录 |

**第二期（推荐后续接入）：**

| 方式 | 集成成本 | 说明 |
|------|----------|------|
| Slack Webhook | 低 (~2h) | POST JSON 到 Slack |
| 飞书/钉钉 Webhook | 低 (~2h) | 国内团队首选 |
| 邮件 (smtplib) | 低 (~1h) | 简单可靠 |
| Telegram Bot | 低 (~1h) | 个人运维者 |

### 6.3 告警延迟等级与响应

| 严重度 | 响应 SLA | 升级路径 |
|--------|----------|----------|
| CRITICAL (P99>120s / 服务全挂) | 15min 内响应 | 立即 SSH / systemctl status |
| WARN (P95>60s / 拒答>5%) | 2h 内确认 | 次日日报分析根因 |
| INFO (缓存命中率低) | 下个迭代 | 优化缓存策略 |

---

## 7. 交付物清单

### 7.1 脚本文件

| # | 文件路径 | 类型 | 说明 |
|---|----------|------|------|
| 1 | `backend/scripts/health_check.sh` | Shell | 每 5 分钟健康检查 + 自愈 |
| 2 | `backend/scripts/collect_metrics.py` | Python | 查询指标聚合 (从 audit_log) |
| 3 | `backend/scripts/daily_report.py` | Python | 日报生成 (Markdown) |
| 4 | `backend/scripts/cron_collect_metrics.sh` | Shell | cron 包装脚本 (指标采集) |
| 5 | `backend/scripts/cron_daily_report.sh` | Shell | cron 包装脚本 (日报生成) |

### 7.2 输出目录结构

```
/home/ubuntu/kb2-web/
└── logs/
    ├── health.log               # 健康检查日志 (持续追加)
    ├── .health_alert            # 告警标记文件 (存在 = CRITICAL)
    ├── cron_metrics.log         # 指标采集 cron 日志
    ├── cron_report.log          # 日报 cron 日志
    ├── metrics/
    │   └── 2026-07-08.json      # 每日指标 JSON
    └── reports/
        └── 2026-07-08.md        # 每日日报 Markdown
```

### 7.3 配置变更

| # | 变更对象 | 变更内容 | 说明 |
|---|----------|----------|------|
| 6 | `crontab` | 新增 3 条 cron 条目 | health, metrics, report |
| 7 | `kb2-web.service` | 确认 Restart 配置 | 可选增强 |

### 7.4 文档

| # | 文件 | 说明 |
|---|------|------|
| 8 | `docs/l05-ops-observability.md` | 本方案文档 |

---

## 8. 工时估计

### 8.1 开发工时

| 任务 | 工时 (人·时) | 依赖 | 负责人 |
|------|-------------|------|--------|
| **P1: 健康检查** | **4h** | - | 运维/后端 |
| ├─ 编写 health_check.sh | 1.5h | - | |
| ├─ 配置 cron | 0.5h | health_check.sh | |
| └─ 验证 systemd 自动重启 | 2h | kb2-web.service | |
| **P2: 指标采集** | **6h** | - | 后端 |
| ├─ 实现 collect_metrics.py | 3h | audit_log 表现用字段 | |
| ├─ 编写 cron 包装脚本 | 0.5h | collect_metrics.py | |
| ├─ 测试 SQL 聚合查询 | 1h | DB 连通 | |
| └─ 首日历史数据回填 | 1.5h | collect_metrics.py | |
| **P3: 日报生成** | **3h** | P2 完成 | 后端 |
| ├─ 实现 daily_report.py | 2h | collect_metrics.py 输出 | |
| └─ 编写 cron 包装脚本 | 1h | daily_report.py | |
| **P4: 告警集成** | **4h** | P1–P3 | 运维 |
| ├─ 实施阈值逻辑（hardcode 日报内） | 1h | daily_report.py | |
| ├─ 异常/边界行为验证 | 2h | 全流程 | |
| └─ 编写操作手册 (runbook) | 1h | 全流程 | |
| **P5: 测试与验证** | **3h** | P1–P4 | QA/后端 |
| ├─ 健康检查故障注入测试 | 1h | P1 | |
| ├─ 指标准确性验证 | 1h | P2 | |
| └─ 日报格式验证 | 1h | P3 | |

### 8.2 总计

| 阶段 | 工时 | 日历参考 (1 人) |
|------|------|-----------------|
| **开发** | 17h | 2.5 工作日 |
| **测试** | 3h | 同开发期 |
| **合计** | **20h** | **3 工作日内交付** |

### 8.3 第二期预算（推荐）

| 任务 | 工时 | 说明 |
|------|------|------|
| 接入 Slack/飞书 Webhook | 2h | 告警通知 |
| 可视化 Dashboard (Grafana) | 8h | SQLite → Grafana |
| 日志集中化 (Loki/Syslog) | 4h | 弃用本地文件 |
| **二期合计** | **14h** | 可按需拆分 |

---

## 9. 附录：SQL 查询 & 脚本参考

### 9.1 核心 SQL 查询（可直接用于验证）

```sql
-- 日聚合
SELECT
    DATE(created_at) AS day,
    COUNT(*) AS total,
    COUNT(DISTINCT user_id) AS users,
    ROUND(AVG(response_ms), 1) AS avg_latency,
    SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END) AS cache_hit,
    SUM(tokens_used) AS tokens
FROM audit_log
WHERE created_at >= '2026-07-08' AND created_at < '2026-07-09'
GROUP BY day;

-- 小时聚合
SELECT
    strftime('%H', created_at) AS hour,
    COUNT(*) AS queries,
    ROUND(AVG(response_ms), 1) AS avg_latency_ms,
    SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END) AS cache_hit
FROM audit_log
WHERE DATE(created_at) = '2026-07-08'
GROUP BY hour
ORDER BY hour;

-- 百分位延迟（SQLite 不支持内置 percentile，用 Python 排序后取索引）
-- 参考 collect_metrics.py 中的实现

-- 拒答类型分布
SELECT rejected, COUNT(*) AS cnt
FROM audit_log
WHERE rejected IS NOT NULL AND DATE(created_at) = '2026-07-08'
GROUP BY rejected
ORDER BY cnt DESC;

-- 高频查询 Top-20
SELECT query, COUNT(*) AS cnt
FROM audit_log
WHERE DATE(created_at) = '2026-07-08'
GROUP BY query
ORDER BY cnt DESC
LIMIT 20;
```

### 9.2 故障排查命令

```bash
# 检查服务状态
sudo systemctl status kb2-web.service
sudo journalctl -u kb2-web.service -n 50 --no-pager

# 查看最新健康检查日志
tail -20 /home/ubuntu/kb2-web/logs/health.log

# 查看告警状态
cat /home/ubuntu/kb2-web/logs/.health_alert 2>/dev/null || echo "无告警"

# 查看最新日报
ls -lt /home/ubuntu/kb2-web/logs/reports/ | head -3

# 手动触发指标采集（某日）
python3 /home/ubuntu/kb2-web/backend/scripts/collect_metrics.py 2026-07-08

# 手动生成日报
python3 /home/ubuntu/kb2-web/backend/scripts/daily_report.py 2026-07-08

# 手动健康检查
bash /home/ubuntu/kb2-web/backend/scripts/health_check.sh

# 查看当日指标 JSON
cat /home/ubuntu/kb2-web/logs/metrics/$(date '+%Y-%m-%d').json

# DB 直查
sqlite3 /home/ubuntu/kb-web/data/kb.db "SELECT COUNT(*) FROM audit_log WHERE date(created_at)='2026-07-08'"
```

### 9.3 关键审计日志字段释义

| 字段 | 类型 | 含义 | 备注 |
|------|------|------|------|
| `response_ms` | INT | 从收到请求到返回回答的端到端耗时(毫秒) | 0 可能表示缓存命中极快或异常 |
| `cache_hit` | INT | 0=未命中, 1=精确命中, 2=语义命中 | 语义命中是向量缓存 |
| `rejected` | VARCHAR(32) | 拒答类型，如 `knowledge_gap`, `low_coverage` | NULL 表示正常回答 |
| `tokens_used` | INT | LLM 调用消耗的 token 数 | 仅实际调用 LLM 时有值 |
| `created_at` | DATETIME | 查询时间戳 (UTC) | 所有时间窗口以此为准 |

---

## 变更历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| v1.0 | 2026-07-09 | Hermes Agent | 初版 — 完整 L05 运维观测实施方案 |
