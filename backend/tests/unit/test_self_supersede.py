"""supersedes 自引用 —— 回归测试（第 4 批）。

缺陷：upload 流程先 commit 新文档，再调 detect_existing_doc()（不排除自身）
⇒ 新文档匹配到自己 ⇒ supersedes 指向自身。生产实证 121 行（占非空 86%）。
后果：get_version_history 无防环 ⇒ 死循环（经 API 暴露）。

本文件锁三件事：
  ① 写侧：exclude_doc_id 排除自身（三条规则），但不过度过滤真实旧版本；
  ② 读侧：自引用/环不得导致不收敛（用线程 + 超时断言，避免测试自身挂死）；
  ③ 兼容：不传 exclude_doc_id 时行为不变（证明修复点是该参数，非其他副作用）。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from app.models.document import Document
from app.services.version_chain import detect_existing_doc, get_version_history


def _add(db, doc_id, *, title="测试文档", bank="general", doc_type="generic",
         content_hash="", status="active", supersedes=None, superseded_by=None):
    db.add(Document(
        doc_id=doc_id, title=title, bank=bank, doc_type=doc_type,
        content_hash=content_hash, status=status,
        supersedes=supersedes, superseded_by=superseded_by,
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()


def _call_with_timeout(fn, seconds=5):
    """在线程里跑 fn；超时即判为未收敛（不挂死测试进程）。"""
    box = {}

    def _run():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), box


# ── ① 写侧：排除自身 ────────────────────────────────────────
def test_detect_excludes_self_by_content_hash(db_session):
    """规则 1：新文档的 hash 与自身相同 ⇒ 排除自身后应返回 None。"""
    _add(db_session, "new-001", content_hash="same-hash")
    assert detect_existing_doc(
        db_session, title="测试文档", bank="general",
        content_hash="same-hash", exclude_doc_id="new-001",
    ) is None


def test_detect_excludes_self_by_title(db_session):
    """规则 3：同 bank + 同标题命中自身 ⇒ 排除自身后应返回 None。"""
    _add(db_session, "new-002", title="唯一标题", content_hash="")
    assert detect_existing_doc(
        db_session, title="唯一标题", bank="general", exclude_doc_id="new-002",
    ) is None


def test_detect_excludes_self_by_standard_number(db_session):
    """规则 2：GB 标准号命中自身 ⇒ 排除自身后应返回 None。"""
    _add(db_session, "new-003", title="GB/T 50116-2013 火灾自动报警",
         doc_type="gb_standard")
    assert detect_existing_doc(
        db_session, title="GB/T 50116-2013 火灾自动报警", bank="general",
        doc_type="gb_standard", exclude_doc_id="new-003",
    ) is None


def test_detect_still_finds_real_old_version(db_session):
    """★ 反向核：排除自身不得误伤真实旧版本。"""
    _add(db_session, "old-001", title="同名文档", content_hash="hash-x")
    _add(db_session, "new-004", title="同名文档", content_hash="hash-x")
    found = detect_existing_doc(
        db_session, title="同名文档", bank="general",
        content_hash="hash-x", exclude_doc_id="new-004",
    )
    assert found is not None, "应命中真实旧版本，不得被排除逻辑吃掉"
    assert found.doc_id == "old-001"


def test_detect_without_exclude_returns_self(db_session):
    """兼容/成因锚：不传 exclude_doc_id 时自匹配依旧发生。

    这条**故意断言旧行为**——它证明「自引用」的成因而非别处，
    也保证文档化：修正是 exclude_doc_id 这个参数带来的。
    """
    _add(db_session, "new-005", content_hash="self-hash")
    found = detect_existing_doc(
        db_session, title="测试文档", bank="general", content_hash="self-hash",
    )
    assert found is not None and found.doc_id == "new-005"


# ── ② 读侧：不收敛 → 收敛 ───────────────────────────────────
def test_version_history_self_ref_terminates(db_session):
    """自引用文档：必须返回（原实现在此死循环）。"""
    _add(db_session, "self-ref-1", supersedes="self-ref-1")
    finished, box = _call_with_timeout(
        lambda: get_version_history(db_session, "self-ref-1"), 5
    )
    assert finished, "get_version_history 未在 5s 内返回 = 死循环回归"
    assert "result" in box, f"抛异常: {box.get('error')}"
    res = box["result"]
    assert len(res["chain"]) == 1, f"自引用链长应为 1，实为 {len(res['chain'])}"
    assert res["supersedes"] is None, "不得把自身回显为 supersedes"


def test_version_history_two_node_cycle_terminates(db_session):
    """两节点环 a.supersedes=b、b.supersedes=a：必须收敛且不重复计数。"""
    _add(db_session, "cyc-a", supersedes="cyc-b")
    _add(db_session, "cyc-b", supersedes="cyc-a")
    finished, box = _call_with_timeout(
        lambda: get_version_history(db_session, "cyc-a"), 5
    )
    assert finished, "环未收敛 = 防环失效"
    res = box["result"]
    ids = [c["doc_id"] for c in res["chain"]]
    assert len(ids) == len(set(ids)), f"链中出现重复节点: {ids}"


def test_version_history_two_node_cycle_downward_terminates(db_session):
    """★ 前向环（superseded_by 方向）：防环必须两向都生效。"""
    _add(db_session, "dcyc-a", superseded_by="dcyc-b")
    _add(db_session, "dcyc-b", superseded_by="dcyc-a")
    finished, box = _call_with_timeout(
        lambda: get_version_history(db_session, "dcyc-a"), 5
    )
    assert finished, "前向环未收敛 = 前向防环失效"
    res = box["result"]
    ids = [c["doc_id"] for c in res["chain"]]
    assert len(ids) == len(set(ids)), f"链中出现重复节点: {ids}"


def test_version_history_self_ref_superseded_by_hidden(db_session):
    """superseded_by 自指同样不得回显为自身。"""
    _add(db_session, "self-down", superseded_by="self-down")
    finished, box = _call_with_timeout(
        lambda: get_version_history(db_session, "self-down"), 5
    )
    assert finished, "未收敛"
    assert box["result"]["superseded_by"] is None


def test_version_history_normal_chain_unaffected(db_session):
    """★ 反向核：正常链行为不变（chain 序 = 最新→最旧，与既有用例一致）。"""
    _add(db_session, "v1-001", title="V1")
    _add(db_session, "v2-001", title="V2", supersedes="v1-001")
    _add(db_session, "v3-001", title="V3", supersedes="v2-001")
    res = get_version_history(db_session, "v3-001")
    assert [c["doc_id"] for c in res["chain"]] == ["v3-001", "v2-001", "v1-001"]
    assert res["supersedes"]["doc_id"] == "v2-001"
    assert res["superseded_by"] is None


def test_version_history_normal_downward_unaffected(db_session):
    """★ 反向核：向下（新版本）方向遍历行为不变。"""
    _add(db_session, "w1-001", title="W1", superseded_by="w2-001")
    _add(db_session, "w2-001", title="W2", supersedes="w1-001")
    res = get_version_history(db_session, "w1-001")
    assert [c["doc_id"] for c in res["chain"]] == ["w2-001", "w1-001"]
    assert res["superseded_by"]["doc_id"] == "w2-001"
