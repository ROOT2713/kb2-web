"""searchable「双口径」收口 —— 读侧一致化单测（第 2 批 / 2026-09-30）

═══════════════════════════════════════════════════════════════════
不变式（本批立此为准）：

    visible = (status='active' AND searchable=1)

语义分解：``searchable`` 是**合取项** ——
  ① 质量门通过（``_verify_searchable`` 覆盖率 ≥80% 且 pg 可见）
  ② 户口有效（``status='active'``）
两半缺一即「不可检索」。实测（2026-09-30 /home/ubuntu/kb-web/data/kb.db）：

    active     + searchable=1 → 124   （真·可检索）
    active     + searchable=0 →   4   （① 未过，合法为 0）
    stale      + searchable=1 →  99   ← 漂移
    superseded + searchable=1 → 379   ← 漂移

⇒ 漂移 478 行；全仓 19 处检索谓词写全了两半，**5 处只写了 ①**（漏 status）。
   漂移的**危害全由这 5 条读路径兑现**（写侧只负责让它持续增长）：

   1. ``query_engine`` 标题模糊匹配候选池 → superseded 标题抢占 best_doc，
      targeted recall 落空（结果被 _filter_invisible 滤掉）= 静默降召回
   2. ``query_engine._assemble_standard_contents_meta`` → 注意
      ``_get_invisible_doc_ids()`` 查询失败时 **fail-open 放行全部**
      （retrieval.py:278）⇒ 此时 searchable=1（=漂移值）成唯一门槛，
      superseded 全文可被注入 LLM 上下文
   3. ``query_engine._generate_query_suggestions`` related_docs → **用户可见**：
      向用户推荐已 superseded/stale 的旧规范名
   4. ``query.standard-full`` → 可直接拉取 superseded 全文
   5. ``banks.list_banks`` → 前端「可检索」数字虚高（602 vs 124）

本文件：4/5 走**行为断言**，1/2 因埋在大函数内不可达 → 走**源码级防回退锁**
（harness-templates：源码锁不是行为测试，两种都要有）。

⚠️ 本文件用**独立内存库**（覆盖 conftest 同名 fixture）：用例真实 commit，
conftest 的外层事务 rollback 撤不掉 → 会污染全 session 共享引擎。
"""
import pytest
from pathlib import Path

from app.models.document import Document, ParentChunk

_BACKEND = Path(__file__).resolve().parents[2]
_APP = _BACKEND / "app"


@pytest.fixture()
def db_session():
    """本文件专用**独立**内存库（覆盖 conftest 的同名 fixture）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.database import Base

    import app.models.document  # noqa: F401
    import app.models.concept   # noqa: F401
    import app.models.cache     # noqa: F401
    import app.models.synonym   # noqa: F401

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
def iso_db(db_session, monkeypatch):
    """把 query / query_engine 的模块级 ``SessionLocal`` 指到隔离库。

    两个模块都是模块顶 ``from app.models.database import SessionLocal``
    （值拷贝导入）⇒ patch 源模块无效，必须 patch 消费模块属性。
    """
    import app.api.query as q_mod
    import app.api.query_engine as qe_mod

    monkeypatch.setattr(q_mod, "SessionLocal", lambda: db_session, raising=False)
    monkeypatch.setattr(qe_mod, "SessionLocal", lambda: db_session, raising=False)
    return db_session


def _seed(db_session, **overrides):
    """建一条文档（默认 active + searchable=1，可覆写）。"""
    kw = dict(
        doc_id="d-1", title="GB/T 28449-2018 等级保护测评要求",
        bank="kb_general", status="active", searchable=1,
    )
    kw.update(overrides)
    db_session.add(Document(**kw))
    db_session.commit()


# ═══════════════════════════════════════════════════════════════════
# 3. related_docs 规范提醒 —— 用户可见输出
# ═══════════════════════════════════════════════════════════════════

def _related_doc_ids() -> list:
    from app.api.query_engine import _generate_query_suggestions

    out = _generate_query_suggestions("等保测评怎么做", bank="all")
    return [d["doc_id"] for d in out.get("related_docs", [])]


def test_related_docs_excludes_superseded(iso_db):
    """superseded 文档（searchable 仍为 1 = 漂移形态）不得出现在规范提醒里。"""
    _seed(iso_db, doc_id="d-sup", status="superseded", searchable=1)
    assert "d-sup" not in _related_doc_ids()


def test_related_docs_excludes_stale(iso_db):
    """stale 文档（父本由自净空每日产生）不得出现在规范提醒里。"""
    _seed(iso_db, doc_id="d-stale", status="stale", searchable=1)
    assert "d-stale" not in _related_doc_ids()


def test_related_docs_excludes_draft_and_deprecated(iso_db):
    """模型允许 draft/deprecated —— 同样必须从提醒里排除（原先只卡 searchable）。"""
    _seed(iso_db, doc_id="d-draft", status="draft", searchable=1)
    _seed(iso_db, doc_id="d-dep", status="deprecated", searchable=1)
    ids = _related_doc_ids()
    assert "d-draft" not in ids and "d-dep" not in ids


def test_related_docs_includes_active_control(iso_db):
    """阳性对照：active + searchable=1 必须仍然出现（防「一律排除」的假修复）。"""
    _seed(iso_db, doc_id="d-ok", status="active", searchable=1)
    ids = _related_doc_ids()
    assert ids == ["d-ok"], f"阳性对照失败，related_docs={ids}"


# ═══════════════════════════════════════════════════════════════════
# 2. _assemble_standard_contents_meta —— fail-open 时的唯一兜底
# ═══════════════════════════════════════════════════════════════════

def _assemble(iso_db):
    from app.api.query_engine import _assemble_standard_contents_meta

    return _assemble_standard_contents_meta(
        [{"doc": "GB/T 28449-2018 等级保护测评要求", "doc_id": "d-gb"}],
        bank="all",
    )


def test_standard_meta_excludes_superseded(iso_db):
    """superseded 文档不得被组装成「规范全文」注入 LLM。

    _get_invisible_doc_ids() fail-open 时本函数是唯一兜底，故断言必须钉在此处。
    """
    _seed(iso_db, doc_id="d-gb", status="superseded", searchable=1,
          title="GB/T 28449-2018 等级保护测评要求")
    iso_db.add(ParentChunk(doc_id="d-gb", parent_idx=0, parent_text="旧版正文" * 50))
    iso_db.commit()
    assert _assemble(iso_db) == []


def test_standard_meta_includes_active_control(iso_db):
    """阳性对照：active 文档仍能被组装。"""
    _seed(iso_db, doc_id="d-gb", status="active", searchable=1,
          title="GB/T 28449-2018 等级保护测评要求")
    iso_db.add(ParentChunk(doc_id="d-gb", parent_idx=0, parent_text="现行正文" * 50))
    iso_db.commit()
    got = _assemble(iso_db)
    assert len(got) == 1 and got[0]["doc_id"] == "d-gb"


# ═══════════════════════════════════════════════════════════════════
# 4. GET /query/standard-full/{doc_id}
# ═══════════════════════════════════════════════════════════════════

def test_standard_full_404_for_superseded(client, iso_db):
    _seed(iso_db, doc_id="d-sup", status="superseded", searchable=1)
    iso_db.add(ParentChunk(doc_id="d-sup", parent_idx=0, parent_text="旧版全文" * 50))
    iso_db.commit()
    r = client.get("/api/query/standard-full/d-sup")
    assert r.status_code == 404, f"superseded 全文不应可拉取，得 {r.status_code}"


def test_standard_full_200_for_active(client, iso_db):
    _seed(iso_db, doc_id="d-ok", status="active", searchable=1)
    iso_db.add(ParentChunk(doc_id="d-ok", parent_idx=0, parent_text="现行全文" * 50))
    iso_db.commit()
    r = client.get("/api/query/standard-full/d-ok")
    assert r.status_code == 200, f"active 文档应可拉取，得 {r.status_code}: {r.text[:200]}"
    assert "现行全文" in r.json().get("full_text", "")


# ═══════════════════════════════════════════════════════════════════
# 5. GET /api/banks —— 统计口径
# ═══════════════════════════════════════════════════════════════════

def test_banks_searchable_cnt_excludes_non_active(client, iso_db, monkeypatch):
    """searchable_cnt 只数 active；cnt（总数）不受影响。"""
    import app.api.banks as banks_mod

    monkeypatch.setattr(
        banks_mod, "_refresh_banks",
        lambda: {"all": {"name": "全部"}, "kb_general": {"name": "综合"}},
    )
    _seed(iso_db, doc_id="d-1", status="active", searchable=1)
    _seed(iso_db, doc_id="d-2", status="superseded", searchable=1)  # 漂移形态
    _seed(iso_db, doc_id="d-3", status="stale", searchable=1)       # 漂移形态
    _seed(iso_db, doc_id="d-4", status="active", searchable=0)      # 质量门未过

    body = client.get("/api/banks").json()
    row = next(b for b in body["banks"] if b["key"] == "kb_general")
    assert row["count"] == 4, "总数口径不得被收窄"
    assert row["searchable"] == 1, f"searchable 应只数 active，得 {row['searchable']}"

    allrow = next(b for b in body["banks"] if b["key"] == "all")
    assert allrow["searchable"] == 1


# ═══════════════════════════════════════════════════════════════════
# 1 / 6. 源码级防回退锁（两处埋在大函数内，行为不可达 → 源码锁）
# ═══════════════════════════════════════════════════════════════════

def _src(rel: str) -> str:
    return (_APP / rel).read_text(encoding="utf-8")


def test_source_lock_title_fuzzy_pool_has_status():
    """标题模糊匹配候选池：searchable=1 必须与 status='active' 同行。

    ⚠️ 锚点必须用**完整调用形态**：只断言
    ``WHERE searchable=1 AND status='active'`` 会被 L307/L336 的合法谓词命中
    → 回退代码后断言仍绿（假阳性，已由突变测试实测抓出）。
    """
    src = _src("api/query_engine.py")
    anchor = 'sa_text("SELECT doc_id, title FROM documents ' \
             'WHERE searchable=1 AND status=\'active\'")'
    assert anchor in src, \
        "候选池 SQL 又漏了 status（superseded 标题会抢占 best_doc）"


def test_source_lock_upload_dedup_is_active_scoped():
    """上传去重必须只按 active 判重；过宽的 get_by_hash 二次查重已被删除。"""
    src = _src("api/upload.py")
    assert "get_by_hash" not in src, "过宽的二次查重又回来了（会误拒 superseded 内容的重新上传）"
    assert 'Document.status == "active"' in src, "active 判重必须保留"


def test_source_lock_all_five_read_sites_have_status():
    """五处读侧谓词一次性锁定，任一被回退即红。"""
    qe = _src("api/query_engine.py")
    q = _src("api/query.py")
    b = _src("api/banks.py")
    assert "AND status='active' AND ({conditions})" in qe          # related_docs
    assert "d.searchable = 1 AND d.status = 'active'" in qe        # standard meta
    assert "doc_id=:doc_id AND searchable=1 AND status='active'" in q
    assert "SUM(CASE WHEN searchable=1 AND status='active'" in b
