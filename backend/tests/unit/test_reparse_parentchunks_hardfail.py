"""reparse 的 ``parent_chunks`` 写入必须**硬失败**，不得静默降级为 warning。

═══════════════════════════════════════════════════════════════════
缺陷（2026-10-15 实测 · 修复前形态）：

``app/api/documents.py::reparse_document`` 里 ``parent_chunks`` 的写入被
try/except 包住，``except`` 只 ``logger.warning("Failed to save parent_chunks")``
就继续往下走 ⇒ 产出「**有向量、无父段**」的半成品文档，而端点照旧返回 **200**。

实测受害文档：GB 50462-2024（``bafd21f8-…``）
    documents      : chunk_count=542, searchable=1, status=active
    parent_chunks  : **0 行**            ← 缺陷
    pg vector_chunks: 542 行              ← 向量都在

为什么这是真问题（不是洁癖）：
  ``retrieval.py:467/499`` 明写「构建 BM25 索引 —— **主来源**：meta.db parent_chunks」，
  ``:549`` 才 fallback 到语义召回 ⇒ 父段为 0 的文档**被排除在主检索路径之外**，
  只剩纯语义召回可能碰到它。全库「active ∧ searchable=1 ∧ 零父段」曾为 1 篇。

本文件是修复的回归锁，四层：
  ① 写入异常       → 端点必须 5xx（不得 200），且**不得**继续去嵌入向量
  ② 写入不完整     → 回验计数不符时端点必须 5xx（新增的回验分支）
  ③ 阳性对照       → 正常路径仍 200 且父段**真落库**（防「一律拒绝」式过修）
  ④ 原子性         → 失败时旧文档不得被删除

突变核验（手工执行，证明 ① 有牙齿）：
  把 except 块改回 ``logger.warning("Failed to save parent_chunks: %s", e)``
  → ① 必须变红（拿到 200）。
═══════════════════════════════════════════════════════════════════
"""

from pathlib import Path

import pytest
from sqlalchemy import text as _real_text

from app.models.document import Document, ParentChunk

OLD_DOC_ID = "old-reparse-pc-1"
DOC_TITLE = "测试标准 GB 50462"
FILENAME = "GB_50462-test.pdf"
# 正文含章节标题，保证 heading_chunk / parent_child_chunk 至少产出 1 个父段
CLEAN_TEXT = (
    "# 测试标准 GB 50462\n\n"
    "## 1 总则\n"
    "数据中心基础设施施工及验收应满足本标准的全部条款。\n"
    "电力供应系统应满足不间断运行要求。\n\n"
    "## 2 术语\n"
    "地震动：地震引起的地表及近地表介质的振动。\n"
    "数据中心：为集中放置电子信息系统设备并保证其正常运行环境的场所。\n"
)

DOCUMENTS_PY = Path(__file__).resolve().parents[2] / "app" / "api" / "documents.py"


# ═══════════════════════════════════════════════════════════════════
# 夹具：独立内存库（端点会真实 commit，conftest 的外层 rollback 撤销不了）
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture()
def db_session():
    """本文件专用**独立**内存库（覆盖 conftest 同名 fixture）。

    reparse 端点内部会 ``db.commit()``（父段写入、``repo.save()``），
    conftest 的「外层事务 rollback」无法撤销这类写入 → 残留行会污染
    全 session 共享引擎。改用独立引擎后，本文件怎么 commit 都不影响其它用例。
    """
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
    s = sessionmaker(bind=eng, autocommit=False, autoflush=False)()
    yield s
    s.close()
    eng.dispose()


# ═══════════════════════════════════════════════════════════════════
# 故障注入：用「指向不存在列 / 恒假谓词」的等价 SQL 替换目标语句
# ═══════════════════════════════════════════════════════════════════

_INSERT_MARK = "INSERT OR REPLACE INTO parent_chunks"
_COUNT_MARK = "SELECT COUNT(*) FROM parent_chunks"


def _failing_sa_text(mode):
    """返回 ``sa_text`` 替身：只改写目标语句，其余原样透传。"""
    def _fake(sql):
        if mode == "insert_error" and _INSERT_MARK in sql:
            # 引用不存在的列 → 真实 SQLite 抛 OperationalError（模拟写失败）
            return _real_text(
                "INSERT OR REPLACE INTO parent_chunks "
                "(doc_id, parent_idx, parent_text, nope_col) VALUES (:did, :idx, :ptext, 1)"
            )
        if mode == "count_zero" and _COUNT_MARK in sql:
            # 回验恒返 0 → 触发「写入不完整」分支
            return _real_text(
                "SELECT COUNT(*) FROM parent_chunks WHERE doc_id = :did AND 1=0"
            )
        return _real_text(sql)
    return _fake


def _run_reparse(client, db_session, tmp_path, monkeypatch, sa_text_mode=None,
                 empty_chunks=False):
    """搭好旧文档 + 打桩外部依赖，跑**一次**真实 reparse 端点。

    返回 ``(response, upserted)``；``upserted`` 记录向量库是否被调用及条数
    （用于断言「父段写入失败后不得继续嵌入」）。
    ``empty_chunks=True`` 时把两个分块器都打桩成返回 []（模拟「输入侧无父段」变体）。
    """
    from app.api import documents
    from app.config import settings

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)
    (upload_dir / FILENAME).write_bytes(b"%PDF-1.4 fake content")
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    db_session.add(Document(
        doc_id=OLD_DOC_ID,
        title=DOC_TITLE,
        bank="general",
        hs_bank="kb_general",
        status="active",
        searchable=1,
        filename=FILENAME,
        category="standard",
    ))
    db_session.commit()

    async def _fake_parse(_filename, _content):
        return CLEAN_TEXT

    monkeypatch.setattr(documents, "parse_document", _fake_parse)

    upserted = {}

    class _FakeStore:
        async def delete(self, *_a, **_k):
            return 0

        async def upsert(self, doc_id, items, bank):
            upserted["doc_id"] = doc_id
            upserted["count"] = len(items)
            return len(items)

    monkeypatch.setattr(documents, "get_vector_store", lambda: _FakeStore())

    async def _noop_verify(*_a, **_k):
        return True

    monkeypatch.setattr(documents, "_verify_searchable", _noop_verify)
    monkeypatch.setattr(documents, "invalidate_bm25_cache", lambda **_k: None)
    monkeypatch.setattr(documents, "invalidate_query_cache_by_bank", lambda *_a, **_k: None)
    monkeypatch.setattr(settings, "vector_backend", "pgvector")

    if sa_text_mode:
        monkeypatch.setattr(documents, "sa_text", _failing_sa_text(sa_text_mode))

    if empty_chunks:
        monkeypatch.setattr(documents, "heading_chunk", lambda *_a, **_k: [])
        monkeypatch.setattr(documents, "parent_child_chunk", lambda *_a, **_k: [])

    resp = client.post(f"/api/documents/{OLD_DOC_ID}/reparse")
    return resp, upserted


# ═══════════════════════════════════════════════════════════════════
# ① 写入异常 → 必须 5xx（缺陷的直接观测点）
# ═══════════════════════════════════════════════════════════════════

class TestParentChunksWriteFailureIsHard:

    def test_insert_error_returns_5xx_not_200(self, client, db_session, tmp_path, monkeypatch):
        """父段 INSERT 抛错时，端点必须 5xx —— 修复前是 200（静默半成品）。"""
        resp, _ = _run_reparse(
            client, db_session, tmp_path, monkeypatch, sa_text_mode="insert_error"
        )
        assert resp.status_code >= 500, (
            f"parent_chunks 写入失败时端点返回 {resp.status_code}，应 5xx。"
            f"返回 200 即重现「有向量、无父段」的静默半成品缺陷。body={resp.text[:300]}"
        )
        # CC-Q6：不得把底层 DB 异常原文（含表名/列名）回传给客户端
        assert "nope_col" not in resp.text and "no such column" not in resp.text.lower(), (
            f"500 响应体泄漏了底层 DB 异常细节：{resp.text[:300]}"
        )

    def test_insert_error_aborts_before_embedding(self, client, db_session, tmp_path, monkeypatch):
        """失败必须在**嵌入之前**中止（父段写入在上游），不白烧 embedding 配额。"""
        _, upserted = _run_reparse(
            client, db_session, tmp_path, monkeypatch, sa_text_mode="insert_error"
        )
        assert not upserted, (
            f"父段写入失败后仍调用了向量库（{upserted}）——应在嵌入前即中止"
        )

    def test_insert_error_keeps_old_document_intact(self, client, db_session, tmp_path, monkeypatch):
        """④ 原子性：失败时旧文档不得被删除（先建新再删旧，失败即保留旧）。"""
        _run_reparse(
            client, db_session, tmp_path, monkeypatch, sa_text_mode="insert_error"
        )
        old = db_session.query(Document).filter(Document.doc_id == OLD_DOC_ID).first()
        assert old is not None, "父段写入失败后旧文档消失了 —— 破坏了「失败不丢文档」的原子性"
        assert db_session.query(Document).count() == 1, "失败路径不应新建文档行"

    # ── ② 新增的回验分支：写入「成功」但行数不符也必须失败 ──

    def test_incomplete_write_returns_5xx(self, client, db_session, tmp_path, monkeypatch):
        """回验计数不符（期望 N 行、实得 0 行）时必须 5xx —— 这条分支是本次新增的。"""
        resp, _ = _run_reparse(
            client, db_session, tmp_path, monkeypatch, sa_text_mode="count_zero"
        )
        assert resp.status_code >= 500, (
            f"parent_chunks 写入不完整时端点返回 {resp.status_code}，应 5xx。"
            f"body={resp.text[:300]}"
        )

    # ── ②b 输入侧变体：分块本身没产出父段（回验 `0 != 0` 恒假，抓不到）──

    def test_empty_parent_map_returns_5xx(self, client, db_session, tmp_path, monkeypatch):
        """CC-Q2：分块未产出任何父段时必须 5xx —— 否则只是换条路径产出同样的无父段文档。"""
        resp, upserted = _run_reparse(
            client, db_session, tmp_path, monkeypatch, empty_chunks=True
        )
        assert resp.status_code >= 500, (
            f"父段为空时端点返回 {resp.status_code}，应 5xx。body={resp.text[:300]}"
        )
        assert not upserted, "父段为空时仍去嵌入向量（应在嵌入前中止）"
        old = db_session.query(Document).filter(Document.doc_id == OLD_DOC_ID).first()
        assert old is not None, "父段为空时旧文档被删除（应保持原子性）"

    # ── ③ 阳性对照：正常路径不得被「一律拒绝」式过修波及 ──

    def test_normal_path_persists_parent_chunks(self, client, db_session, tmp_path, monkeypatch):
        """正常路径：200 + 父段真落库 + 向量必被写入。防过修（把正常路径也拒了）。"""
        resp, upserted = _run_reparse(client, db_session, tmp_path, monkeypatch)
        assert resp.status_code == 200, f"正常路径失败: {resp.status_code} {resp.text[:300]}"
        assert upserted.get("count", 0) > 0, "正常路径未向向量库写入任何 chunk"

        new_doc_id = resp.json().get("new_doc_id") or upserted["doc_id"]
        rows = (
            db_session.query(ParentChunk)
            .filter(ParentChunk.doc_id == new_doc_id)
            .all()
        )
        assert rows, (
            f"新文档 {new_doc_id} 无 parent_chunks 行 —— 正是本次修复要杜绝的形态"
        )
        assert any((r.parent_text or "").strip() for r in rows), "父段全为空文本"

    # ── 源码锁：防回退到「静默 warning」 ──

    def test_source_does_not_swallow_parentchunks_failure(self):
        """源码锁：不得再出现「只 warning 不抛」的 parent_chunks 失败处理。"""
        src = DOCUMENTS_PY.read_text(encoding="utf-8")
        assert 'logger.warning("Failed to save parent_chunks' not in src, (
            "parent_chunks 失败处理回退成了静默 warning（必须硬失败）"
        )
        assert "parent_chunks 写入失败，已中止" in src, (
            "未找到硬失败分支的标记串 —— 修复可能被回退"
        )
