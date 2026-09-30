#!/usr/bin/env python3
"""存量 supersedes 自引用 —— 修复前分析与 dry-run（只读，绝不写）。

121 行 `supersedes = doc_id`（自指）是 upload.py 调用点无条件赋值造成的。
其中一部分**真实旧版本可从反向链恢复**：若存在 Y 满足
`Y.superseded_by = X` 且 `Y.doc_id != X`，则 X.supersedes 的正确值就是 Y
（因为 Y 被 X 替代是权威记录）。其余无可恢复信息 ⇒ 置 NULL。

用法：
    python3 repair_self_supersede.py            # dry-run（默认，只报告）
    python3 repair_self_supersede.py --apply    # 真正写库（需显式授权）
"""
import shutil
import sqlite3
import sys
from datetime import datetime

DB = "/home/ubuntu/kb-web/data/kb.db"
APPLY = "--apply" in sys.argv


def main():
    # 只读分析
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    selfref = con.execute(
        "SELECT doc_id, title, status, superseded_by FROM documents "
        "WHERE supersedes = doc_id"
    ).fetchall()

    recoverable, to_null = [], []
    amb = 0
    for doc_id, title, status, sby in selfref:
        # 重复上传的同名标准会产出多个候选；实测 208 个候选**全部** status='superseded'
        # ⇒ 任取皆合法。这里钉成「最近的前驱」（created_at 降序，ROWID 兜底）以获得
        # 确定性 + 语义可解释（直接前驱），并加 status 守卫防未来数据漂移。
        cands = con.execute(
            "SELECT doc_id, title FROM documents "
            "WHERE superseded_by = ? AND doc_id != ? AND status = 'superseded' "
            "ORDER BY created_at DESC, ROWID DESC",
            (doc_id, doc_id),
        ).fetchall()
        if len(cands) > 1:
            amb += 1
        prev = cands[0] if cands else None
        if prev:
            recoverable.append((doc_id, title, prev[0], prev[1]))
        else:
            to_null.append((doc_id, title, status))

    print(f"自引用行数 = {len(selfref)}")
    print(f"  可恢复（反向链 Y.superseded_by=X 存在）: {len(recoverable)}")
    print(f"  置 NULL（无任何信息）                : {len(to_null)}")
    print(f"  其中反向链歧义（多候选，取最近前驱）  : {amb}")
    print(f"\n可恢复样例（前 5）:")
    for x, xt, y, yt in recoverable[:5]:
        print(f"  {x[:12]} «{(xt or '')[:26]}»  supersedes 应为 {y[:12]} «{(yt or '')[:22]}»")
    print(f"\n置 NULL 样例（前 5）:")
    for x, xt, st in to_null[:5]:
        print(f"  {x[:12]} [{st}] «{(xt or '')[:30]}»")
    print(f"\n状态分布（置 NULL 组）:")
    for st, n in con.execute(
        "SELECT status, COUNT(*) FROM documents WHERE supersedes = doc_id GROUP BY status"
    ).fetchall():
        print(f"  {st}: {n}")
    con.close()

    if not APPLY:
        print("\n[dry-run] 未写库。加 --apply 执行（需显式授权）。")
        print("执行前会自动备份 DB。")
        return 0

    # ── 写库 ──────────────────────────────────────────────────
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    bak = f"{DB}.selfref_bak.{stamp}"
    shutil.copy2(DB, bak)
    print(f"\n[备份] {bak}")

    con = sqlite3.connect(DB)
    n_rec = 0
    for doc_id, _t, prev_id, _pt in recoverable:
        cur = con.execute(
            "UPDATE documents SET supersedes = ? WHERE doc_id = ? AND supersedes = ?",
            (prev_id, doc_id, doc_id),
        )
        n_rec += cur.rowcount
    cur = con.execute(
        "UPDATE documents SET supersedes = NULL WHERE supersedes = doc_id"
    )
    n_null = cur.rowcount
    con.commit()

    left = con.execute(
        "SELECT COUNT(*) FROM documents WHERE supersedes = doc_id"
    ).fetchone()[0]
    print(f"[写库] 恢复链接 {n_rec} 行；置 NULL {n_null} 行；残留自引用 = {left}")
    con.close()
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
