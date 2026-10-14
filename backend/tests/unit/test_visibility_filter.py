"""D3 可见性过滤测试 — searchable 门禁对语义检索生效。

覆盖：
- _filter_invisible 剔除户口不可见（superseded / searchable=0）doc 的 chunk
- 无不可见 doc 时全量放行
- recall() 在 pgvector 定向 bank 路径应用过滤
"""

import pytest

from app.services import retrieval


class _FakeRows:
    """模拟 db.execute(text(...)).fetchall() 返回值。"""

    def __init__(self, ids):
        self._ids = ids

    def fetchall(self):
        return [(i,) for i in self._ids]


class _FakeSession:
    """模拟单会话内的**两次** SELECT（_refresh_invisible_cache）。

      ① `... WHERE status != 'active' OR searchable != 1` → 不可见集合
      ② `SELECT doc_id FROM documents`（无 WHERE）        → 全量户口集合【FIX-ORPHAN】
    以「语句里有无 WHERE」区分二者。
    """

    def __init__(self, invisible_ids, known_ids=None):
        self._invisible = _FakeRows(invisible_ids)
        # 缺省用不可见集合充当户口集合；要表达"某 id 可见"必须显式传 known_ids
        self._known = _FakeRows(known_ids if known_ids is not None else invisible_ids)

    def execute(self, stmt):
        return self._invisible if "WHERE" in str(stmt).upper() else self._known

    def close(self):
        pass


def _mk_result(doc_id, text="内容"):
    return {"text": text, "tags": [f"doc_id:{doc_id}", "chunk:0"], "score": 0.9}


class TestFilterInvisible:
    def test_removes_invisible_docs(self, monkeypatch):
        """黑名单 doc_id (superseded/searchable=0) 的 chunk 被剔除，可见的保留。"""
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession(["a", "b"], known_ids=["a", "b", "c"]))
        # 清缓存，强制重新查询
        retrieval._invisible_cache["ts"] = 0.0

        results = [
            _mk_result("a"),
            _mk_result("b"),
            _mk_result("c"),
            _mk_result("c"),
        ]
        out = retrieval._filter_invisible(results)
        assert [r["tags"][0] for r in out] == ["doc_id:c", "doc_id:c"]

    def test_no_invisible_keeps_all(self, monkeypatch):
        """无不可见 doc 时全量放行。"""
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession([], known_ids=["x", "y"]))
        retrieval._invisible_cache["ts"] = 0.0

        results = [_mk_result("x"), _mk_result("y")]
        out = retrieval._filter_invisible(results)
        assert len(out) == 2

    def test_missing_doc_id_tag_kept(self, monkeypatch):
        """无 doc_id 标签的 chunk 无法归属，保守放行。"""
        monkeypatch.setattr(retrieval, "SessionLocal", lambda: _FakeSession(["a"]))
        retrieval._invisible_cache["ts"] = 0.0

        orphan = {"text": "无归属", "tags": ["chunk:3"], "score": 0.5}
        out = retrieval._filter_invisible([orphan, _mk_result("a")])
        assert len(out) == 1
        assert out[0] == orphan

    def test_cache_ttl(self, monkeypatch):
        """30s TTL 内复用缓存，不重复查库。"""
        calls = {"n": 0}

        class CountingSession(_FakeSession):
            def __init__(self, ids):
                super().__init__(ids)
                calls["n"] += 1

        monkeypatch.setattr(retrieval, "SessionLocal", lambda: CountingSession(["a"]))
        retrieval._invisible_cache["ts"] = 0.0

        retrieval._filter_invisible([_mk_result("a")])
        retrieval._filter_invisible([_mk_result("a")])
        assert calls["n"] == 1

    def test_db_error_fails_open(self, monkeypatch):
        """查库异常时告警并放行全部（fail-open，保证检索可用性）。"""
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(retrieval, "SessionLocal", _boom)
        retrieval._invisible_cache["ts"] = 0.0

        out = retrieval._filter_invisible([_mk_result("a")])
        assert len(out) == 1


class TestRecallPgvectorFilter:
    @pytest.mark.asyncio
    async def test_recall_specific_bank_filters_invisible(self, monkeypatch):
        """pgvector 定向 bank 路径：召回结果中黑名单 doc 被剔除。"""
        monkeypatch.setattr("app.config.settings.vector_backend", "pgvector")
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession(["bad-doc"],
                                                 known_ids=["bad-doc", "good-doc"]))
        retrieval._invisible_cache["ts"] = 0.0

        class FakeStore:
            async def query(self, query_text, bank, top_k):
                return [
                    _mk_result("bad-doc", "被隔离的旧版"),
                    _mk_result("good-doc", "正常内容"),
                ]

        monkeypatch.setattr(retrieval, "get_vector_store", lambda: FakeStore())
        # recall() all-banks 分支用 isinstance(store, PgVectorStore) 判断，
        # FakeStore 不是 PgVectorStore 实例会落到真 PgVectorStore() 连库 →
        # 必须同时 patch PgVectorStore 类本身（函数内 import，调用时解析）。
        monkeypatch.setattr("app.repositories.vector_repo.PgVectorStore", FakeStore)
        # BANKS 映射需要可解析，用真实配置中的 general 键
        monkeypatch.setattr(retrieval, "BANKS", {"general": {"hindsight": "kb_general"}})

        out = await retrieval.recall(query="测试", bank="general", limit=5)
        assert len(out) == 1
        assert out[0]["tags"][0] == "doc_id:good-doc"

    @pytest.mark.asyncio
    async def test_recall_all_banks_filters_invisible(self, monkeypatch):
        """pgvector all-banks 并行路径：合并结果同样过可见性过滤。"""
        monkeypatch.setattr("app.config.settings.vector_backend", "pgvector")
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession(["bad-doc"],
                                                 known_ids=["bad-doc", "good-doc"]))
        retrieval._invisible_cache["ts"] = 0.0

        class FakeStore:
            async def query(self, query_text, bank, top_k):
                return [
                    _mk_result("bad-doc", "旧版碎片"),
                    _mk_result("good-doc", "有效内容"),
                ]

        monkeypatch.setattr(retrieval, "get_vector_store", lambda: FakeStore())
        # all-banks 分支 isinstance 判断需要 PgVectorStore 也指向 FakeStore
        monkeypatch.setattr("app.repositories.vector_repo.PgVectorStore", FakeStore)
        monkeypatch.setattr(retrieval, "BANKS", {
            "general": {"hindsight": "kb_general"},
            "project": {"hindsight": "kb_project"},
        })

        out = await retrieval.recall(query="测试", bank="all", limit=5)
        ids = {r["tags"][0] for r in out}
        assert ids == {"doc_id:good-doc"}


# ═══════════════════════════════════════════════════════════════════
# 【FIX-ORPHAN】pg 有向量但 SQLite 户口已注销的孤儿 doc_id 必须被剔除
#
# 背景：黑名单由「SQLite 现存行的属性」反推 ⇒ 孤儿不在现存行 ⇒ 不在黑名单 ⇒ 原样放行。
# 实测（2026-10-14）：29 个孤儿 doc_id / 459 chunk 全部 registry=1，可进语义召回候选。
# ═══════════════════════════════════════════════════════════════════

class TestFilterOrphans:
    def test_orphan_doc_removed(self, monkeypatch):
        """孤儿（不在全量户口集合内）被剔除；户口内可见文档保留。"""
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession([], known_ids=["good"]))
        retrieval._invisible_cache["ts"] = 0.0

        out = retrieval._filter_invisible([_mk_result("orphan"), _mk_result("good")])
        assert [r["tags"][0] for r in out] == ["doc_id:good"]

    def test_orphan_and_invisible_both_removed(self, monkeypatch):
        """两类剔除同时生效：孤儿（户口已注销）+ 不可见（superseded）。"""
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession(["sup"], known_ids=["sup", "good"]))
        retrieval._invisible_cache["ts"] = 0.0

        out = retrieval._filter_invisible(
            [_mk_result("sup"), _mk_result("ghost"), _mk_result("good")])
        assert [r["tags"][0] for r in out] == ["doc_id:good"]

    def test_all_orphans_dropped(self, monkeypatch):
        """全部候选均为孤儿 ⇒ 返回空列表（而不是退化成"放行全部"）。"""
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession([], known_ids=["other"]))
        retrieval._invisible_cache["ts"] = 0.0

        out = retrieval._filter_invisible([_mk_result("g1"), _mk_result("g2")])
        assert out == []

    def test_fail_open_disables_orphan_check(self, monkeypatch):
        """阴性对照：查库失败 ⇒ known=None ⇒ 放行全部（孤儿判定关闭，不误伤正常候选）。"""
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(retrieval, "SessionLocal", _boom)
        retrieval._invisible_cache["ts"] = 0.0

        out = retrieval._filter_invisible([_mk_result("x"), _mk_result("y")])
        assert len(out) == 2

    @pytest.mark.asyncio
    async def test_recall_specific_bank_filters_orphan(self, monkeypatch):
        """pgvector 定向 bank 路径：孤儿 doc 同样被剔除。"""
        monkeypatch.setattr("app.config.settings.vector_backend", "pgvector")
        monkeypatch.setattr(retrieval, "SessionLocal",
                            lambda: _FakeSession([], known_ids=["good-doc"]))
        retrieval._invisible_cache["ts"] = 0.0

        class FakeStore:
            async def query(self, query_text, bank, top_k):
                return [
                    _mk_result("ghost-doc", "户口已注销的残留向量"),
                    _mk_result("good-doc", "正常内容"),
                ]

        monkeypatch.setattr(retrieval, "get_vector_store", lambda: FakeStore())
        monkeypatch.setattr("app.repositories.vector_repo.PgVectorStore", FakeStore)
        monkeypatch.setattr(retrieval, "BANKS", {"general": {"hindsight": "kb_general"}})

        out = await retrieval.recall(query="测试", bank="general", limit=5)
        assert len(out) == 1
        assert out[0]["tags"][0] == "doc_id:good-doc"
