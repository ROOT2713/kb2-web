"""reparse 端点必须走**完整清洗管线**（``clean_pipeline``），与上传路径同水位。

═══════════════════════════════════════════════════════════════════
缺陷（2026-10-12 实测 · 方向① 文档质量治理）：

``app/api/documents.py::reparse_document`` 只调 ``clean_watermarks(text)``，
**跳过** ``clean_html_residuals`` / ``clean_page_artifacts`` / ``normalize_whitespace``
等步骤；而 ``app/api/upload.py:297`` 走 ``clean_pipeline(text, source_hint=filename)``。
⇒ 同一份 PDF 经两条路径入库，产出**不一致**：

    实测 GB 50343（reparse 后）：7,467 个 HTML 标签残留、3,790 个表格标签，
                                 中文占比仅 **24.8%**
    实测 GB 50343（upload 后）：0 标签、表格转管道格式、中文占比正常

后果：reparse 是「文本完整但分块薄」类文档的**唯一修复正道**
（``upload.py:328-333`` 查重闸门会把这类重传拒收），
若它不清洗，则每次 reparse 都把 HTML 噪声重新灌进检索库。

本文件是修复的回归锁，两层：
  ① **行为测试** —— 跑真实端点，断言送去向量库的 chunk 无 HTML 标签（有牙齿）
  ② **阳性对照** —— 同一跑次断言正文存活，防「全删」式过修
  ③ **源码锁** —— 防回退到只调 ``clean_watermarks``

突变核验（手工执行，证明①有牙齿）：
  把 ``documents.py`` 的 ``clean_pipeline(text, source_hint=filename)``
  改回 ``clean_watermarks(text)`` → ① 必须变红（标签数 24 ≠ 0），③ 必须变红
═══════════════════════════════════════════════════════════════════
"""

import re
from pathlib import Path

import pytest

from app.config import settings
from app.models.document import Document

DOCUMENTS_PY = Path(__file__).resolve().parents[2] / "app" / "api" / "documents.py"

# 「脏」抽取文本 —— 模拟 MinerU 原始输出（HTML 表格 + 内联 style + 注释 + 水印）
# 期望：clean_pipeline 后标签数 = 0，表格转管道格式，正文（防火间距/安全疏散）全保留
DIRTY_TEXT = """# 测试标准 GB 50016

<!-- page 1 -->
<table><tr><td>防火间距</td><td>不应小于 6m</td></tr></table>
<span style="color:red">耐火等级</span> 应符合本规范第 3.2 节的规定。

<table>
<tr><td>安全疏散</td><td>距离</td></tr>
<tr><td>疏散楼梯</td><td>10m</td></tr>
</table>

扫描全能王 创建
第 2 页 共 10 页
"""

# 正文特征串 —— 阳性对照：清洗后必须仍然存在
BODY_MARKERS = ("防火间距", "不应小于 6m", "安全疏散", "疏散楼梯", "耐火等级")

# 「标签」判定：`<` + 字母/斜杠 + 非 `>` 内容 + `>`。
# 注意 **不** 匹配 `<!- ->`（清洗后的 HTML 注释残留），与 clean_html_residuals 口径一致。
TAG_RE = re.compile(r"<[a-zA-Z/][^>]{0,200}>")


@pytest.fixture()
def db_session():
    """本文件专用**独立**内存库（覆盖 conftest 同名 fixture）。

    reparse 端点会真实 ``commit()``（``DocumentRepository.save()`` 内部 commit、
    端点内 ``db.commit()``），conftest 的「外层事务 rollback」无法撤销这类写入
    → 残留行会污染全 session 共享引擎（表格是 session 级，只建一次）。
    改用独立引擎后，本文件怎么 commit 都不影响其它用例。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.database import Base

    # 导入**全部**模型以注册 metadata（缺 users 会让 require_role 认证失败）
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


@pytest.fixture()
def captured_chunks(client, db_session, tmp_path, monkeypatch):
    """跑**一次**真实 reparse 端点，捕获送去向量库的 chunk 内容。

    全部外部依赖打桩：解析器返回固定「脏」文本、向量库假实现只捕获不落库、
    质量门/缓存失效置空 —— 唯一真实的是**清洗 + 分块**这两步（缺陷所在层）。
    """
    from app.api import documents

    # ① 原件落盘到临时 upload_dir（端点要求原件存在，否则 404）
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    filename = "GB_50016-test.pdf"
    (upload_dir / filename).write_bytes(b"%PDF-1.4 fake content")
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    # ② 建旧文档行（端点会读 meta，再删旧、建新）
    db_session.add(Document(
        doc_id="old-reparse-clean-1",
        title="测试标准 GB 50016",
        bank="general",
        hs_bank="kb_general",
        status="active",
        searchable=1,
        filename=filename,
        category="standard",
    ))
    db_session.commit()

    # ③ 假解析器 → 返回固定「脏」文本
    async def _fake_parse(_filename, _content):
        return DIRTY_TEXT

    monkeypatch.setattr(documents, "parse_document", _fake_parse)

    # ④ 假向量库 → 捕获 upsert 入参（即「最终建索引的内容」）
    captured = {}

    class _FakeStore:
        async def delete(self, *_a, **_k):
            return 0

        async def upsert(self, doc_id, items, bank):
            captured["items"] = items
            captured["bank"] = bank
            return len(items)

    monkeypatch.setattr(documents, "get_vector_store", lambda: _FakeStore())

    # ⑤ 隔离副作用（质量门异步任务 / 缓存失效）
    async def _noop_verify(*_a, **_k):
        return True

    monkeypatch.setattr(documents, "_verify_searchable", _noop_verify)
    monkeypatch.setattr(documents, "invalidate_bm25_cache", lambda **_k: None)
    monkeypatch.setattr(documents, "invalidate_query_cache_by_bank", lambda *_a, **_k: None)

    # ⑥ 强制走 pgvector 分支（否则 upsert 不被调用，捕获为空）
    monkeypatch.setattr(settings, "vector_backend", "pgvector")

    resp = client.post("/api/documents/old-reparse-clean-1/reparse")
    assert resp.status_code == 200, (
        f"reparse 端点失败: {resp.status_code} {resp.text[:400]}"
    )

    items = captured.get("items", [])
    assert items, "reparse 未向向量库写入任何 chunk（客户端打桩失效，测试无效）"
    return items


def _all_text(items):
    return "\n".join(it["content"] for it in items)


# ═══════════════════════════════════════════════════════════════════
# ① 行为测试：reparse 落库的 chunk 不得含 HTML 标签（缺陷的直接观测点）
# ═══════════════════════════════════════════════════════════════════

class TestReparseChunksAreCleaned:

    def test_no_html_tags_in_indexed_chunks(self, captured_chunks):
        """所有入索引 chunk 的 HTML 标签数必须为 0。

        实测缺陷形态：只走 clean_watermarks 时 24 个标签（2 个 <table> + 6 个 <td>
        + <span>/<div>/<p> 等）会原样进库 → 本断言变红。
        """
        offenders = []
        for it in captured_chunks:
            tags = TAG_RE.findall(it["content"])
            if tags:
                offenders.append((tags[:5], it["content"][:120]))
        assert not offenders, (
            f"{len(offenders)}/{len(captured_chunks)} 个 chunk 残留 HTML 标签"
            f"（reparse 未走完整清洗管线）：\n"
            + "\n".join(f"  标签{s} … {c!r}" for s, c in offenders[:3])
        )

    def test_table_structure_preserved_as_pipe_format(self, captured_chunks):
        """表格必须转成管道格式（信息不丢），而不是简单剥标签。

        clean_html_residuals 的第一步 _html_table_to_pipe 负责该转换；
        只走 clean_watermarks 时表格仍是裸 <table> → 本断言变红。
        """
        text = _all_text(captured_chunks)
        assert "<table" not in text.lower(), "表格标签未转换"
        assert re.search(r"\|\s*防火间距\s*\|", text), (
            f"表格未转为管道格式，单元格关系丢失。实际片段:\n{text[:300]}"
        )

    # ② 阳性对照：证明「不是靠全删过关」
    def test_body_text_survives_cleaning(self, captured_chunks):
        """正文特征串必须全部存活 —— 防止「把内容删光」也能让上面的断言通过。"""
        text = _all_text(captured_chunks)
        missing = [m for m in BODY_MARKERS if m not in text]
        assert not missing, (
            f"清洗把正文一起删掉了，缺失特征串: {missing}\n实际内容:\n{text[:400]}"
        )

    def test_chunks_not_emptied(self, captured_chunks):
        """chunk 数与非空内容量下界 —— 防「清洗过头导致入库量崩塌」。"""
        assert len(captured_chunks) >= 1
        assert len(_all_text(captured_chunks)) >= 80, (
            f"清洗后总内容仅 {len(_all_text(captured_chunks))} 字符，疑似过修"
        )


# ═══════════════════════════════════════════════════════════════════
# ③ 源码锁：防回退到只调 clean_watermarks（非行为断言，作为补充防线）
# ═══════════════════════════════════════════════════════════════════

class TestReparseSourceUsesCleanPipeline:

    @staticmethod
    def _reparse_body() -> str:
        """取出 reparse_document 函数体源码。"""
        import inspect

        from app.api import documents

        return inspect.getsource(documents.reparse_document)

    def test_reparse_calls_clean_pipeline(self):
        """reparse_document 必须调用 clean_pipeline（与 upload 路径同水位）。"""
        body = self._reparse_body()
        assert "clean_pipeline(" in body, (
            "reparse_document 未调用 clean_pipeline —— 与 upload 路径清洗口径不一致"
        )

    def test_reparse_not_only_clean_watermarks(self):
        """reparse_document 不得仅调用 clean_watermarks（旧缺陷形态）。"""
        body = self._reparse_body()
        assert "clean_watermarks(" not in body, (
            "reparse_document 仍调用 clean_watermarks —— 已回退到缺陷实现"
        )

    def test_documents_module_imports_clean_pipeline(self):
        """模块级 import 必须是 clean_pipeline，且不再引入 clean_watermarks。"""
        src = DOCUMENTS_PY.read_text(encoding="utf-8")
        assert "clean_pipeline" in src, "documents.py 未引入 clean_pipeline"
        assert "from app.utils.text_cleaning import filename_to_title, clean_watermarks" not in src, (
            "documents.py 仍从 text_cleaning 导入 clean_watermarks（旧 import 形态）"
        )


# ═══════════════════════════════════════════════════════════════════
# ④ 缺陷 2：published_date 非空时 reparse 必 500
#     根因：get_meta() 把日期序列化为 ISO **字符串**（JSON 友好），
#           而 documents.published_date 是 DATE 列 → SQLAlchemy 拒绝字符串
#           （TypeError: SQLite Date type only accepts Python date objects）。
#           upload 路径显式转 date（upload.py L227-236 / L483-490），reparse 未转。
#     影响面：全库 active 184 篇中 43 篇（23%）published_date 非空 → 全部无法 reparse。
# ═══════════════════════════════════════════════════════════════════

def _build_reparse_fixture(client, db_session, tmp_path, monkeypatch, with_date: bool):
    """构造一次 reparse 调用，返回 (响应, db_session, 新 doc_id 或 None)。"""
    from datetime import date as _date

    from app.api import documents

    upload_dir = tmp_path / "uploads_date"
    upload_dir.mkdir()
    filename = "GB_50016-date.pdf"
    (upload_dir / filename).write_bytes(b"%PDF-1.4 fake content")
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    kwargs = {}
    if with_date:
        kwargs["published_date"] = _date(2021, 1, 1)
    db_session.add(Document(
        doc_id="old-reparse-date-1",
        title="带日期的测试标准",
        bank="general",
        hs_bank="kb_general",
        status="active",
        searchable=1,
        filename=filename,
        category="standard",
        **kwargs,
    ))
    db_session.commit()

    async def _fake_parse(_filename, _content):
        return "# 测试标准\n\n" + "正文内容若干，用于通过质量门禁，必须超过一百字符。" * 8

    monkeypatch.setattr(documents, "parse_document", _fake_parse)

    class _FakeStore:
        async def delete(self, *_a, **_k):
            return 0

        async def upsert(self, _doc_id, items, _bank):
            return len(items)

    monkeypatch.setattr(documents, "get_vector_store", lambda: _FakeStore())

    async def _noop_verify(*_a, **_k):
        return True

    monkeypatch.setattr(documents, "_verify_searchable", _noop_verify)
    monkeypatch.setattr(documents, "invalidate_bm25_cache", lambda **_k: None)
    monkeypatch.setattr(documents, "invalidate_query_cache_by_bank", lambda *_a, **_k: None)
    monkeypatch.setattr(settings, "vector_backend", "pgvector")

    resp = client.post("/api/documents/old-reparse-date-1/reparse")
    return resp, db_session


@pytest.fixture()
def reparse_with_date(client, db_session, tmp_path, monkeypatch):
    """旧文档带**非空** published_date → 跑 reparse。"""
    return _build_reparse_fixture(client, db_session, tmp_path, monkeypatch, with_date=True)


@pytest.fixture()
def reparse_without_date(client, db_session, tmp_path, monkeypatch):
    """旧文档 published_date 为空 → 跑 reparse（阴性对照，旧实现也能过）。"""
    return _build_reparse_fixture(client, db_session, tmp_path, monkeypatch, with_date=False)


class TestReparsePublishedDateCoercion:

    def test_reparse_with_nonnull_date_succeeds(self, reparse_with_date):
        """published_date 非空时 reparse 必须成功 —— 旧实现抛 500。

        这是缺陷 2 的直接观测点：DATE 列收到 ISO 字符串 → TypeError → 500。
        """
        resp, _db = reparse_with_date
        assert resp.status_code == 200, (
            f"reparse 对非空 published_date 失败（缺陷 2）: "
            f"{resp.status_code} {resp.text[:300]}"
        )

    def test_new_doc_keeps_date_value(self, reparse_with_date):
        """新文档的 published_date 必须是 date 对象且值不变（不得被静默置空）。

        防「把日期一律置 None」这种绕过式修复：值必须原样保留。
        """
        from datetime import date as _date

        resp, db = reparse_with_date
        new_id = resp.json()["new_doc_id"]
        db.expire_all()
        row = db.query(Document).filter_by(doc_id=new_id).one()
        assert isinstance(row.published_date, _date), (
            f"published_date 应为 date，实际 {type(row.published_date).__name__}"
            f"（值 {row.published_date!r}）"
        )
        assert row.published_date == _date(2021, 1, 1), (
            f"日期值被改动: {row.published_date}"
        )

    def test_reparse_without_date_still_works(self, reparse_without_date):
        """阴性对照：published_date 为空时也必须成功（不得因新逻辑反而失败）。"""
        resp, _db = reparse_without_date
        assert resp.status_code == 200, (
            f"无日期文档 reparse 失败: {resp.status_code} {resp.text[:300]}"
        )

    def test_source_has_date_coercion(self):
        """源码锁：reparse_document 必须把 meta 的字符串日期转成 date 对象。"""
        import inspect

        from app.api import documents

        body = inspect.getsource(documents.reparse_document)
        assert "isinstance(_pub_raw, str)" in body or "isinstance(pub_date, str)" in body, (
            "reparse_document 未对 meta 的字符串日期做类型转换（缺陷 2 会复发）"
        )
        assert "date(" in body, "reparse_document 未构造 date 对象"


# ═══════════════════════════════════════════════════════════════════
# ⑤ 缺陷 3：reparse 非原子 —— 先删旧再建新，中途失败即丢文档
#     实测：2026-10-12 批量重解析，第 1、2 篇在 repo.save 处 500，
#           「旧文档已删、新文档未建」→ 3 篇元数据 + 向量永久丢失
#           （文档总数 627 → 624）。修法：破坏性步骤下沉到新文档落库之后。
# ═══════════════════════════════════════════════════════════════════

class TestReparseNonAtomicity:

    def test_old_doc_survives_when_new_doc_creation_fails(
        self, client, db_session, tmp_path, monkeypatch
    ):
        """【F3】新建文档失败时旧文档必须完好 —— 旧实现先删旧 → 文档丢失。"""
        from datetime import date as _date

        from app.api import documents
        from app.repositories.document_repo import DocumentRepository

        upload_dir = tmp_path / "uploads_f3"
        upload_dir.mkdir()
        filename = "GB_50016-f3.pdf"
        (upload_dir / filename).write_bytes(b"%PDF-1.4 fake")
        monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

        db_session.add(Document(
            doc_id="old-f3-1", title="非原子性测试标准", bank="general",
            hs_bank="kb_general", status="active", searchable=1,
            filename=filename, category="standard", published_date=_date(2021, 1, 1),
        ))
        db_session.commit()

        async def _fake_parse(_fn, _c):
            return "# 标准\n\n" + "正文内容若干，必须超过一百字符。" * 10

        monkeypatch.setattr(documents, "parse_document", _fake_parse)

        class _FakeStore:
            async def delete(self, *_a, **_k):
                return 0

            async def upsert(self, *_a, **_k):
                return 1

        monkeypatch.setattr(documents, "get_vector_store", lambda: _FakeStore())

        def _boom(*_a, **_k):
            raise RuntimeError("模拟新建文档失败")

        monkeypatch.setattr(DocumentRepository, "save", _boom)

        # TestClient 默认 raise_server_exceptions=True → 未处理异常会再抛出。
        # 真实服务由 error_handler 中间件转 500。两种形态都算「失败信号」。
        try:
            resp = client.post("/api/documents/old-f3-1/reparse")
            code = resp.status_code
        except Exception:
            code = 500
        assert code >= 500, f"预期失败，实得 {code}"

        db_session.expire_all()
        old = db_session.query(Document).filter_by(doc_id="old-f3-1").first()
        assert old is not None, (
            "❌ 缺陷 3 复现：新建失败后旧文档被删除（数据永久丢失）"
        )
        assert old.status == "active", f"旧文档状态被改动: {old.status}"
        assert old.searchable == 1, f"旧文档 searchable 被改动: {old.searchable}"

    def test_source_orders_delete_after_save(self):
        """源码锁【F3】：删除旧文档必须排在新文档落库（repo.save）之后。"""
        import inspect

        from app.api import documents

        body = inspect.getsource(documents.reparse_document)
        i_save = body.find("repo.save(")
        i_del = body.find("DELETE FROM documents WHERE doc_id")
        assert i_save != -1, "未找到 repo.save 调用"
        assert i_del != -1, "未找到删除旧文档的 SQL"
        assert i_save < i_del, (
            "❌ 删除旧文档排在新建之前（缺陷 3 复发：失败即丢文档）"
        )


