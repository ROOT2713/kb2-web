#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 机制化回归锁（出处: kb2 数据治理 0904 · P2 阶段）

锁定三类修复，防止回退:
  G1  delete/upsert 按 doc_id 全量删向量（不再受 (doc_id, bank) 二元条件漏删）
  G2  删除端点 pg 失败 → 重试 3 次 → 仍失败抛 500 且不删 SQLite 户口
  G3  p2_reconcile 对账逻辑（孤儿 / 僵尸 / bank 残留）
"""
import importlib.util
import pathlib
import sqlite3

import pytest


# ── 工具 ────────────────────────────────────────────────────────
def _load_reconcile():
    p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "p2_reconcile.py"
    spec = importlib.util.spec_from_file_location("p2_reconcile", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCursor:
    """按队列脚本化返回 fetchall / fetchone，并记录执行过的 SQL。"""

    def __init__(self, fetchall_queue=None, fetchone_queue=None):
        self.executed = []
        self._fa = list(fetchall_queue or [])
        self._fo = list(fetchone_queue or [])

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, rows):
        self.executed.append((sql, list(rows)))

    def fetchall(self):
        return self._fa.pop(0) if self._fa else []

    def fetchone(self):
        return self._fo.pop(0) if self._fo else (0,)


def _capture_store():
    """构造 PgVectorStore 替身（绕过 __init__），返回 (store, executed, patch_fn)。"""
    from app.repositories.vector_repo import PgVectorStore

    executed = []

    class FakeConn:
        async def execute(self, sql, *args):
            executed.append((sql, args))
            return "DELETE 3"

        async def executemany(self, sql, rows):
            executed.append((sql, list(rows)))

    class FakeAcq:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *a):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcq()

    async def fake_pool():
        return FakePool()

    store = object.__new__(PgVectorStore)
    store._get_pool = fake_pool
    return store, executed


# ═══════════════════════════════════════════════════════════════════
# G1 向量删除按 doc_id 全量（不带 bank 条件）
# ═══════════════════════════════════════════════════════════════════
class TestVectorDeleteDocIdOnly:
    def test_delete_sql_has_no_bank_condition(self):
        """delete() 必须是 WHERE doc_id = $1，不得带 AND bank。"""
        import asyncio

        store, executed = _capture_store()
        asyncio.run(store.delete("d1", "kb_general"))

        sqls = [s for s, _ in executed]
        assert any("WHERE doc_id = $1" in s for s in sqls), f"未见 doc_id 删除: {sqls}"
        assert not any("AND bank" in s for s in sqls), \
            f"仍带 bank 条件 → 换 bank 残留删不掉（G1 复发）: {sqls}"

    def test_delete_passes_bank_positionally_not_in_where(self):
        """bank 只作日志/兼容，不得出现在 SQL 参数里。"""
        import asyncio

        store, executed = _capture_store()
        asyncio.run(store.delete("d1", "kb_general"))

        for sql, args in executed:
            assert "bank" not in sql.lower().split("where")[-1], \
                f"WHERE 子句仍含 bank: {sql}"
            assert "kb_general" not in args, f"bank 不应作为删除参数: {args}"

    def test_upsert_first_call_deletes_by_doc_id_only(self, monkeypatch):
        """upsert 首批发 append=False → 删旧必须按 doc_id 全量。"""
        import asyncio

        import numpy as np

        store, executed = _capture_store()

        async def fake_emb_batch(texts):
            return [np.array([0.1] * 1024, dtype=np.float32) for _ in texts]

        monkeypatch.setattr(store, "get_embedding_batch", fake_emb_batch)
        asyncio.run(store.upsert("d1", [{"content": "a"}], "kb_standard", append=False))

        del_sqls = [s for s, _ in executed if s.strip().upper().startswith("DELETE")]
        assert del_sqls, "append=False 应执行删除旧 chunk"
        assert all("AND bank" not in s for s in del_sqls), \
            f"upsert 删旧仍带 bank 条件: {del_sqls}"

    def test_upsert_append_skips_delete(self, monkeypatch):
        """append=True（后续批次/重试）不得删旧。"""
        import asyncio

        import numpy as np

        store, executed = _capture_store()

        async def fake_emb_batch(texts):
            return [np.array([0.2] * 1024, dtype=np.float32) for _ in texts]

        monkeypatch.setattr(store, "get_embedding_batch", fake_emb_batch)
        asyncio.run(store.upsert("d1", [{"content": "a"}], "kb_standard", append=True))

        del_sqls = [s for s, _ in executed if s.strip().upper().startswith("DELETE")]
        assert not del_sqls, f"append=True 不应删旧: {del_sqls}"

    def test_registry_default_still_applied(self, monkeypatch):
        """【FIX-0904 回归】写入口仍自动打 registry=1（勿因本次改动丢失）。"""
        import asyncio

        import numpy as np

        store, executed = _capture_store()

        async def fake_emb_batch(texts):
            return [np.array([0.3] * 1024, dtype=np.float32) for _ in texts]

        monkeypatch.setattr(store, "get_embedding_batch", fake_emb_batch)
        asyncio.run(store.upsert("d1", [{"content": "a"}], "kb_standard", append=True))

        inserts = [r for s, r in executed if "INSERT" in s.upper()]
        assert inserts, "应有 INSERT"
        # rows: (doc_id, chunk_index, bank, text, meta, emb)
        meta = inserts[0][0][4]
        assert meta.get("registry") == "1", f"registry 默认标记丢失: {meta}"


# ═══════════════════════════════════════════════════════════════════
# G2 删除端点：pg 失败不再静默（重试 → 抛 500）
# ═══════════════════════════════════════════════════════════════════
class TestDeleteEndpointNotSilent:
    def _src(self):
        import inspect
        from app.api.documents import delete_document
        return inspect.getsource(delete_document)

    def test_has_retry_loop(self):
        src = self._src()
        assert "range(3)" in src, "pg 删除应有重试（首次 + 2 次）"

    def test_raises_on_persistent_failure(self):
        src = self._src()
        assert "NOT deleted" in src, "重试仍失败必须抛错，不得静默继续删户口"
        assert "raise HTTPException" in src

    def test_old_silent_warning_path_gone(self):
        src = self._src()
        assert 'logger.warning("delete_document: pgvector delete failed: %s", e)' not in src, \
            "旧的『只 warning 后照常删户口』路径应已移除（G2 复发源）"


# ═══════════════════════════════════════════════════════════════════
# G3 对账逻辑
# ═══════════════════════════════════════════════════════════════════
class TestReconcileLogic:
    def test_pick_sqlite_prefers_most_documents(self, tmp_path, monkeypatch):
        rec = _load_reconcile()
        small = tmp_path / "small.db"
        big = tmp_path / "big.db"
        for path, n in ((small, 5), (big, 20)):
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE documents (doc_id text)")
            con.executemany("INSERT INTO documents VALUES (?)",
                            [(f"d{i}",) for i in range(n)])
            con.commit()
            con.close()

        monkeypatch.setattr(rec, "SQLITE_CANDIDATES", [str(small), str(big)])
        assert rec.pick_sqlite() == str(big)

    def test_pick_sqlite_skips_non_document_db(self, tmp_path, monkeypatch):
        rec = _load_reconcile()
        other = tmp_path / "other.db"
        good = tmp_path / "good.db"
        con = sqlite3.connect(other)
        con.execute("CREATE TABLE cost_log (id integer)")  # 无 documents 表
        con.commit()
        con.close()
        con = sqlite3.connect(good)
        con.execute("CREATE TABLE documents (doc_id text)")
        con.execute("INSERT INTO documents VALUES ('x')")
        con.commit()
        con.close()

        monkeypatch.setattr(rec, "SQLITE_CANDIDATES", [str(other), str(good)])
        assert rec.pick_sqlite() == str(good)

    def test_check_orphans_counts_and_registry_split(self):
        rec = _load_reconcile()
        cur = FakeCursor(
            fetchall_queue=[[("aaaaaaaa", 3, None), ("bbbbbbbb", 1, None)]],
            fetchone_queue=[(2,)],
        )
        total, ndocs, detail, _oldest, reg = rec.check_orphans(cur, {"keep1"})
        assert total == 4
        assert ndocs == 2
        assert detail == {"aaaaaaaa": 3, "bbbbbbbb": 1}
        assert reg == 2, "registry='1' 行应单独计数（不自动清）"

    def test_check_zombies_only_active_searchable_missing_in_pg(self):
        rec = _load_reconcile()
        cur = FakeCursor(fetchall_queue=[[("d_pg",)]])
        docs = {
            "d_pg": {"status": "active", "searchable": 1, "bank": "kb", "hs_bank": "kb"},
            "d_zombie": {"status": "active", "searchable": 1, "bank": "kb", "hs_bank": "kb"},
            "d_sup": {"status": "superseded", "searchable": 0, "bank": "kb", "hs_bank": "kb"},
            "d_hidden": {"status": "active", "searchable": 0, "bank": "kb", "hs_bank": "kb"},
        }
        assert rec.check_zombies(cur, docs) == ["d_zombie"]

    def test_check_bank_residue(self):
        rec = _load_reconcile()
        cur = FakeCursor(fetchall_queue=[[("d1", ["kb", "kb_general"], 10)]])
        assert rec.check_bank_residue(cur) == [("d1", ["kb", "kb_general"], 10)]

    def test_check_superseded_residue(self):
        rec = _load_reconcile()
        cur = FakeCursor(fetchall_queue=[[("s1", 5)]])
        docs = {"s1": {"status": "superseded", "searchable": 0, "bank": "kb", "hs_bank": "kb"}}
        assert rec.check_superseded_residue(cur, docs) == [("s1", 5)]

    def test_check_superseded_residue_empty_short_circuit(self):
        rec = _load_reconcile()
        cur = FakeCursor()
        docs = {"a": {"status": "active", "searchable": 1, "bank": "kb", "hs_bank": "kb"}}
        assert rec.check_superseded_residue(cur, docs) == []
        assert cur.executed == [], "无 superseded 时不应查 pg"


class TestG5NoBypassBulkDelete:
    """G5 锁：document_repo 不得再出现绕过向量清理的批量删除捷径。

    旧 delete_by_ids() 只删 SQLite documents 行、完全不碰 pg vector_chunks，
    启用即批量产孤儿 → 已删除（2026-09-16）。本测试防其复活。
    """

    @staticmethod
    def _src():
        p = "/home/ubuntu/kb2-web/backend/app/repositories/document_repo.py"
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_delete_by_ids_removed(self):
        src = self._src()
        assert "def delete_by_ids" not in src, \
            "delete_by_ids 已删除（P2-G5），不得重新引入"

    def test_no_bare_bulk_delete_stmt(self):
        """批量 sa_delete(Document) 语句不得存在（绕过向量清理的形态）。"""
        src = self._src()
        assert "sa_delete(Document)" not in src, \
            "禁止直接批量 sa_delete(Document)：必须先清 pg vector_chunks"

    def test_absence_documented(self):
        """留痕注释存在，避免后人重新引入重犯。"""
        assert "【P2-G5】" in self._src()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
