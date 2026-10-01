#!/usr/bin/env python3
"""知识库「到期预警」—— 只读，不改任何状态，不引入新规则。

┌─ 为什么需要它（①stale 自净空方向）────────────────────────────────┐
│ stale_detection.py 的语义是「status='stale' = 退出检索」，且没有自动  │
│ 回归路径 —— 是个**单向棘轮**。而规则 2「最后验证超 90 天」覆盖了几乎  │
│ 所有本地上传文档（它们没有复验入口，verified_at 一次写死）。          │
│ 实测：active 135 篇中，30 天后 44 篇、60 天后 85 篇、90 天后 127 篇   │
│ 将依次退出检索 —— 这不是「知识老化」，是**闭环缺失**：缺一个把「即将  │
│ 失效」提前告知人的反馈通路。                                        │
│                                                                  │
│ 本脚本只补「感知+告知」这一段；「决策/执行」复用既有              │
│ POST /api/admin/stale/restore/{doc_id}（见 app/api/admin.py:373）。 │
│ 属于**零生产代码改动**的解法（用户偏好），且不新增阈值：            │
│ 判定逻辑直接调用服务端同一个 _check_staleness()，杜绝两套规则漂移。  │
└──────────────────────────────────────────────────────────────────┘

输出策略（watchdog 模式）：**无可操作项时静默**（stdout 为空 → 定时任务不发消息）。
仅在出现「临界」或「新过期」条目时才输出，避免周期性噪音。

用法：
    python3 check_stale_expiry.py                 # 默认 warning=75 / stale=90
    python3 check_stale_expiry.py --warn-days 60
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.services.stale_detection import (  # noqa: E402
    DEFAULT_STALE_DAYS,
    _check_staleness,
    _days_since,
)


def _ro_session():
    """只读会话：显式 mode=ro，绝不写库。"""
    url = settings.db_url
    if url.startswith("sqlite:///") and "mode=ro" not in url:
        url = url.replace("sqlite:///", "sqlite:///file:") + "?mode=ro&uri=true"
    eng = create_engine(url, connect_args={"timeout": 15})
    return sessionmaker(bind=eng, autocommit=False, autoflush=False)()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-days", type=int, default=75,
                    help="预警窗（比 stale 阈值提前的天数）")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    args = ap.parse_args()

    if args.warn_days >= args.stale_days:
        print(f"[参数错误] warn-days({args.warn_days}) 必须小于 stale-days({args.stale_days})")
        return 2

    now = datetime.now(timezone.utc)
    warn_cutoff = now - timedelta(days=args.warn_days)
    hard_cutoff = now - timedelta(days=args.stale_days)

    db = _ro_session()
    try:
        active = db.execute(select(Document).where(Document.status == "active")).scalars().all()
        stale = db.execute(select(Document).where(Document.status == "stale")).scalars().all()
    finally:
        db.close()

    # 同一套规则，只换 cutoff —— 得到「即将到期」与「已到期」
    approaching, expired = [], []
    for d in active:
        r_hard = _check_staleness(d, hard_cutoff, now)
        if r_hard:
            expired.append((d, r_hard, _days_since(d, now)))
            continue
        r_warn = _check_staleness(d, warn_cutoff, now)
        if r_warn:
            approaching.append((d, r_warn, _days_since(d, now)))

    # 最紧急（距上次活动最久）排前
    approaching.sort(key=lambda x: -x[2])
    expired.sort(key=lambda x: -x[2])

    # 净空速率：近 N 天新增 stale（按 stale_at）
    recent_days = 30
    since = now - timedelta(days=recent_days)
    new_stale = 0
    for d in stale:
        sa = d.stale_at
        if sa is None:
            continue
        if sa.tzinfo is None:
            sa = sa.replace(tzinfo=timezone.utc)
        if sa >= since:
            new_stale += 1

    # watchdog：无可操作项 → 静默
    if not approaching and not expired:
        return 0

    out = []
    out.append(f"📚 知识库到期预警 {now.astimezone().strftime('%Y-%m-%d %H:%M')}")
    out.append(
        f"active={len(active)}  已 stale={len(stale)}（近{recent_days}天新增 {new_stale}）  "
        f"临界({args.warn_days}-{args.stale_days}天)={len(approaching)}  "
        f"已过期未标记={len(expired)}"
    )

    if expired:
        out.append("")
        out.append(f"🔴 已过 {args.stale_days} 天（**不会**再被自动置 stale —— 自动过期已于 2026-10-01 停用，须人工决定）：")
        for d, r, dy in expired[:10]:
            out.append(f"   {d.doc_id[:8]}  {d.title[:32]}  ← 最后活动 {dy} 天前")
        if len(expired) > 10:
            out.append(f"   … 另有 {len(expired) - 10} 篇")

    if approaching:
        out.append("")
        out.append(f"🟡 临界（{args.warn_days}–{args.stale_days} 天，即将退出检索，按紧迫度排序）：")
        for d, r, dy in approaching[:10]:
            out.append(f"   {d.doc_id[:8]}  {d.title[:32]}  ← 最后活动 {dy} 天前")
        if len(approaching) > 10:
            out.append(f"   … 另有 {len(approaching) - 10} 篇")

    out.append("")
    out.append("复验后恢复检索：POST /api/admin/stale/restore/{doc_id}（管理员）")
    out.append("仅告警，未改动任何状态。")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
