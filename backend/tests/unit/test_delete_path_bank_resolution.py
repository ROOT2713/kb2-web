"""删除 / 清向量路径的物理库解析 —— 单测（含 ④ 接线级行为断言）

═══════════════════════════════════════════════════════════════════
★ 本文件记录了一次**被推翻的方案**（2026-09-30，CC 对抗审查 + 实测复核）：

  初版把本缺陷叙述为「哨兵 "kb" 当库名 → 从错的库删 → 真库残留孤儿」，
  并据此加了 fail-fast（端点 422 / supersede 跳过清理）。
  **该前提对当前 pgvector 后端不成立**：
    ``PgVectorStore.delete`` 自 FIX-P2-G1（``20a0ef7``，2026-09-16）起执行
    ``DELETE FROM vector_chunks WHERE doc_id = $1`` —— doc_id 是 UUID（全局
    唯一），**bank 仅冗余属性、不参与 WHERE**；旧实现按 ``(doc_id, bank)``
    二元条件删才正是孤儿复发源。
  ⇒ 「从错的库删」不可能发生；初版的 422 / 跳过清理会把**旧代码按 doc_id
    能正确删掉的行**变成「拒绝删 / 不清向量」—— 属**净回归**，已撤销。

  现行语义：``resolve_delete_hs_bank`` 只用于**日志与兼容**，
  **绝不抛错、绝不阻断**；不可解析时返回 ``""`` 并告警。
  它的价值在于「日志里不再出现误导性的哨兵 kb」，而非「防孤儿」。

  本文件用**独立内存库**（覆盖 conftest 同名 fixture）：删除端点内部
  ``DocumentRepository.delete()`` 会真实 commit，conftest 的外层事务
  rollback 无法撤销 → 会污染全 session 共享引擎。
═══════════════════════════════════════════════════════════════════
"""

import pytest

from app.models.document import Document
from app.services.bank_resolver import KNOWN_HS_BANKS, resolve_delete_hs_bank


@pytest.fixture()
def db_session():
    """本文件专用**独立**内存库（覆盖 conftest 的同名 fixture）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.database import Base

    import app.models.audit  # noqa: F401
    import app.models.cache  # noqa: F401
    import app.models.concept  # noqa: F401
    import app.models.document  # noqa: F401
    import app.models.synonym  # noqa: F401
    import app.models.upload_task  # noqa: F401
    import app.models.user  # noqa: F401

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    # 原始 SQL 表（ORM 不建）：删除端点会清理 concept_contradictions
    from sqlalchemy import text as _sa_text
    from app.services.crystallization_light import CREATE_TABLE_SQL, INDEX_SQL

    with eng.begin() as conn:
        conn.execute(_sa_text(CREATE_TABLE_SQL))
        for stmt in INDEX_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(_sa_text(stmt))
    s = sessionmaker(bind=eng, autocommit=False, autoflush=False)()
    yield s
    s.close()
    eng.dispose()


class _FakeStore:
    """记录被调用的 (doc_id, bank)；不触碰真实 pgvector。"""

    def __init__(self):
        self.calls = []

    async def delete(self, doc_id, bank):
        self.calls.append((doc_id, bank))
        return True


@pytest.fixture()
def fake_store(monkeypatch):
    """documents.py L35 是**模块顶** import（名字已值拷贝进命名空间）
    ⇒ 必须 patch **消费模块属性**，patch 源模块静默失效。"""
    import app.api.documents as docs

    store = _FakeStore()
    monkeypatch.setattr(docs, "get_vector_store", lambda: store)
    return store


@pytest.fixture()
def pg_mode(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vector_backend", "pgvector", raising=False)
    return settings


def _mk_doc(db_session, doc_id, bank="general", hs_bank="kb_general", status="active"):
    """建测试文档。

    ⚠️ ``Document.hs_bank`` 有**模型默认值** ``"kb_general"``（document.py:24）
    ⇒ 传 ``None`` 会被默认值接管、测不到「空值」路径；要构造真空值必须显式
    传 ``""``（显式值覆盖默认）。
    """
    doc = Document(
        doc_id=doc_id,
        title=f"测试文档 {doc_id}",
        bank=bank,
        hs_bank=hs_bank,
        status=status,
        searchable=1,
    )
    db_session.add(doc)
    db_session.commit()
    return doc


# ═══════════════════════════════════════════════════════════════════
# ① 纯函数：已知库直用 / 哨兵与空 → 派生 / 垃圾不直用 / 绝不抛错
# ═══════════════════════════════════════════════════════════════════

class TestResolveDeleteHsBank:

    def test_known_bank_used_as_is(self):
        """已知物理库直用（不要求与 bank 自洽 —— 存量 38 行历史态不该被锁死）。"""
        assert resolve_delete_hs_bank("general", "kb_checklist") == "kb_checklist"

    def test_known_bank_used_when_bank_unresolvable(self):
        assert resolve_delete_hs_bank("no_such_bank", "kb_industry") == "kb_industry"

    def test_sentinel_derives_from_bank(self):
        assert resolve_delete_hs_bank("general", "kb") == "kb_general"
        assert resolve_delete_hs_bank("personal", "kb") == "kb_xhs"

    def test_empty_derives_from_bank(self):
        assert resolve_delete_hs_bank("general", None) == "kb_general"
        assert resolve_delete_hs_bank("general", "") == "kb_general"
        assert resolve_delete_hs_bank("general", "   ") == "kb_general"

    def test_case_and_whitespace_normalized(self):
        """大小写/空白归一 —— 否则 'KB' 会绕过哨兵判定、' KB_GENERAL ' 会被当垃圾。"""
        assert resolve_delete_hs_bank("general", "KB") == "kb_general"      # 大写哨兵
        assert resolve_delete_hs_bank("general", " KB_GENERAL ") == "kb_general"
        assert resolve_delete_hs_bank("general", "Kb_Checklist") == "kb_checklist"

    def test_garbled_value_not_trusted(self):
        """『非空非哨兵』≠『真实物理库』—— 拼写错的库名必须走派生，不得直用。"""
        assert resolve_delete_hs_bank("general", "kb_genral") == "kb_general"
        assert resolve_delete_hs_bank("general", "garbage") == "kb_general"

    @pytest.mark.parametrize(
        "bank,hs",
        [("all", ""), ("all", "kb"), ("all", "garbage"), (None, None),
         ("", ""), ("unknown_x", None), ("unknown_x", "nope")],
    )
    def test_unresolvable_returns_empty_and_never_raises(self, bank, hs):
        """两者都不可用 → 返回空串（**不抛错**：pgvector 按 doc_id 删除，
        bank 不影响结果，阻断只会把能删的行变成删不掉）。"""
        out = resolve_delete_hs_bank(bank, hs)
        assert out == ""
        assert isinstance(out, str)

    def test_result_always_known_bank_or_empty(self):
        """返回值必须 ∈ KNOWN_HS_BANKS ∪ {""}（防垃圾值穿透到日志/兼容层）。"""
        for bank, hs in [("general", "kb"), ("general", "kb_checklist"),
                         ("all", "garbage"), ("personal", "KB")]:
            assert resolve_delete_hs_bank(bank, hs) in (KNOWN_HS_BANKS | {""})


# ═══════════════════════════════════════════════════════════════════
# ② 接线级：DELETE 端点把解析结果传给 store，且**永不因解析失败而拒绝删**
# ═══════════════════════════════════════════════════════════════════

class TestDeleteEndpointUsesResolvedBank:

    @pytest.mark.parametrize(
        "bank,hs_bank,expected",
        [
            ("general", "kb", "kb_general"),              # 哨兵 → 派生（日志不再显示 kb）
            ("general", "", "kb_general"),                # 真空值 → 派生
            ("general", "kb_checklist", "kb_checklist"),  # 已知库 → 直用
            ("personal", "kb_xhs", "kb_xhs"),             # 正常透传
            ("general", "KB", "kb_general"),              # 大写哨兵 → 派生
        ],
        ids=["sentinel", "empty", "known-inconsistent", "normal", "upper-sentinel"],
    )
    def test_delete_passes_resolved_bank_to_store(
        self, client, db_session, fake_store, pg_mode, bank, hs_bank, expected
    ):
        doc_id = f"del-{bank}-{hs_bank}"
        _mk_doc(db_session, doc_id, bank=bank, hs_bank=hs_bank)

        resp = client.delete(f"/api/documents/{doc_id}")

        assert resp.status_code == 200, f"{resp.status_code} {resp.text[:200]}"
        assert fake_store.calls == [(doc_id, expected)], (
            f"传给向量库的库名应为 {expected!r}，实得 {fake_store.calls!r}"
        )

    @pytest.mark.parametrize(
        "bank,hs_bank", [("all", ""), ("all", "kb"), ("unknown_x", "")],
        ids=["aggregate-empty", "aggregate-sentinel", "unknown-empty"],
    )
    def test_delete_still_succeeds_when_unresolvable(
        self, client, db_session, fake_store, pg_mode, bank, hs_bank
    ):
        """★ 反向断言（推翻初版）：解析失败**不得**阻断删除。

        pgvector 删除按 doc_id、bank 不参与 ⇒ 拒绝删属净回归。
        期望：仍 200、store.delete 被调用（库名为 ""）、户口已删。
        """
        doc_id = f"del-unresolvable-{bank}-{hs_bank}"
        _mk_doc(db_session, doc_id, bank=bank, hs_bank=hs_bank)

        resp = client.delete(f"/api/documents/{doc_id}")

        assert resp.status_code == 200, f"不得因解析失败拒绝删: {resp.status_code} {resp.text[:200]}"
        assert fake_store.calls == [(doc_id, "")], (
            f"仍应调用向量删除（库名空串），实得 {fake_store.calls!r}"
        )
        assert db_session.query(Document).filter(Document.doc_id == doc_id).first() is None

    def test_delete_404_when_doc_missing(self, client, db_session, fake_store, pg_mode):
        """不存在的文档 → 404（旧行为是 200 + 静默成功）。"""
        resp = client.delete("/api/documents/does-not-exist-1234")
        assert resp.status_code == 404
        assert fake_store.calls == []


# ═══════════════════════════════════════════════════════════════════
# ③ supersede 清向量：**不可解析也必须清**（不得留真孤儿）
# ═══════════════════════════════════════════════════════════════════

class TestSupersedePurgeAlwaysDeletes:

    def _run(self, db_session, monkeypatch, fake_store, old_bank, old_hs):
        import asyncio

        import app.repositories.vector_repo as vr
        import app.services.version_chain as vc

        monkeypatch.setattr(vr, "get_vector_store", lambda: fake_store)
        oid = f"old-{old_bank}-{old_hs}"
        _mk_doc(db_session, oid, bank=old_bank, hs_bank=old_hs)
        _mk_doc(db_session, "new-1", bank="general", hs_bank="kb_general")
        ok = asyncio.run(vc.supersede_and_purge(db_session, oid, "new-1"))
        return oid, ok

    def test_supersede_purges_with_derived_bank_not_kb(
        self, db_session, fake_store, pg_mode, monkeypatch
    ):
        oid, ok = self._run(db_session, monkeypatch, fake_store, "general", "kb")
        assert ok is True
        assert fake_store.calls == [(oid, "kb_general")]

    def test_supersede_purges_even_when_unresolvable(
        self, db_session, fake_store, pg_mode, monkeypatch
    ):
        """★ 反向断言（推翻初版「跳过清理」）：解析失败仍必须调用删除。

        初版在此 `return ok` 跳过清理 ⇒ mark_superseded 已把旧版置 superseded
        但向量永生（FIX-D2 要防的语义永生），而旧代码按 doc_id 本可正确清掉。
        """
        oid, ok = self._run(db_session, monkeypatch, fake_store, "all", "")
        assert ok is True, "不可解析不得阻断 supersede"
        assert fake_store.calls == [(oid, "")], (
            f"不可解析也必须调用删除（库名空串），实得 {fake_store.calls!r}"
        )
