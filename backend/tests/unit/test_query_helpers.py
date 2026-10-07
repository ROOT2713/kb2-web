"""Unit tests for backend.app.api.query helper functions.

Coverage targets (from CC P0 review of feat/chunking-fix-202606):
- _assemble_standard_contents_meta: aggregated SQL correctness vs per-source 3-SQL legacy
- _generate_query_suggestions: rule-hit / no-rule branches + refined_query NOT overwritten by standard_hints[0]

These tests use the in-memory SQLite fixture from conftest.py.
"""

import pytest
from app.api.query import (
    _assemble_standard_contents_meta,
    _generate_query_suggestions,
)
from app.models.document import Document, ParentChunk


# ═══════════════════════════════════════════════════════════════════
# _assemble_standard_contents_meta — 聚合 SQL 等价性
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def seeded_db(db_session, monkeypatch):
    """Seed in-memory DB with 3 docs (2 standards + 1 non-standard) and chunks.

    Patches SessionLocal so query.py picks up the test session.
    """
    # 2 个规范 + 1 个非规范
    docs = [
        # ⚠️ 必须显式设 hs_bank：Document.hs_bank 的模型默认值是 "kb_general"
        # （models/document.py:24）。检索侧按 bank 过滤恒以 hs_bank 为准
        # （db_bank_scope），fixture 若不设会让 bank/hs_bank 自相矛盾
        # （如 bank='standards' 却 hs_bank='kb_general'），既非现实也不可信。
        Document(doc_id="d-gb-001", title="GB 50174-2017 数据中心设计规范",
                 bank="standards", hs_bank="kb_standard", searchable=1),
        Document(doc_id="d-gb-002", title="GB/T 28449-2018 等级保护测评要求",
                 bank="standards", hs_bank="kb_standard", searchable=1),
        Document(doc_id="d-misc",   title="小红书笔记示例",  # 不匹配 _STD_PATTERN
                 bank="general", hs_bank="kb_general", searchable=1),
        Document(doc_id="d-disabled", title="GB 50116-2013 火警规范",
                 bank="standards", hs_bank="kb_standard", searchable=0),  # searchable=0 应被排除
    ]
    chunks = [
        ParentChunk(doc_id="d-gb-001", parent_idx=0, parent_text="第一章 总则。本规范适用于" + "x"*100),
        ParentChunk(doc_id="d-gb-001", parent_idx=1, parent_text="第二章 设计要点" + "y"*200),
        ParentChunk(doc_id="d-gb-002", parent_idx=0, parent_text="等保测评流程概述" + "z"*150),
        ParentChunk(doc_id="d-misc",   parent_idx=0, parent_text="不应被聚合"),
    ]
    for d in docs: db_session.add(d)
    for c in chunks: db_session.add(c)
    db_session.commit()

    # Repoint SessionLocal to test session factory.
    # ⚠️ 必须同时 patch query_engine：_assemble_standard_contents_meta 定义在
    # query_engine 模块、用其自身模块的 SessionLocal；只 patch query.py 时该函数
    # 会另开 session 而看不见本夹具 seed 的数据 ⇒ 任何「断言空列表」的用例都会
    # **假性通过**（vacuous，2026-10-07 发现）。
    import app.api.query as q_mod
    import app.api.query_engine as qe_mod
    monkeypatch.setattr(q_mod, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(qe_mod, "SessionLocal", lambda: db_session)
    return db_session


def test_assemble_standard_contents_meta_basic(seeded_db):
    """规范文件被识别，元数据正确聚合，非规范/未 searchable 被过滤。"""
    sources = [
        {"doc": "GB 50174-2017 数据中心设计规范", "doc_id": "d-gb-001"},
        {"doc": "GB/T 28449-2018 等级保护测评要求", "doc_id": "d-gb-002"},
        {"doc": "小红书笔记示例", "doc_id": "d-misc"},  # 应被 regex 过滤
        {"doc": "GB 50116-2013 火警规范", "doc_id": "d-disabled"},  # searchable=0
    ]
    result = _assemble_standard_contents_meta(sources, bank="all")

    # 只剩 2 个规范文档
    assert len(result) == 2
    ids = [r["doc_id"] for r in result]
    assert ids == ["d-gb-001", "d-gb-002"]  # 顺序按 sources 出现顺序

    # 字段断言
    r1 = result[0]
    assert r1["title"] == "GB 50174-2017 数据中心设计规范"
    assert r1["sections_count"] == 2
    assert r1["total_chars"] > 0
    assert r1["preview"].startswith("第一章 总则")  # parent_idx=0 取第一段


def test_assemble_standard_contents_meta_dedup(seeded_db):
    """重复 doc_id 只算一次。"""
    sources = [
        {"doc": "GB 50174-2017 数据中心设计规范", "doc_id": "d-gb-001"},
        {"doc": "GB 50174-2017 重复", "doc_id": "d-gb-001"},  # 重复
    ]
    result = _assemble_standard_contents_meta(sources, bank="all")
    assert len(result) == 1
    assert result[0]["doc_id"] == "d-gb-001"


def test_assemble_standard_contents_meta_bank_filter(seeded_db):
    """bank=general 时不应返回 standards 文档（hs_bank 维度）。"""
    sources = [
        {"doc": "GB 50174-2017 数据中心设计规范", "doc_id": "d-gb-001"},  # hs_bank=kb_standard
    ]
    result = _assemble_standard_contents_meta(sources, bank="general")
    assert result == []


def test_assemble_standard_contents_meta_hs_bank_decides_visibility(seeded_db):
    """正控（2026-10-07）：可见性由 hs_bank 决定，不由 legacy bank 列决定。

    回归背景：检索侧原按 legacy ``documents.bank`` 列过滤，对 project/personal
    恒 0 命中；收口为 ``db_bank_scope``（按 hs_bank）。本用例证明：
    同一份 legacy bank 取值（standards），只要 hs_bank 落入请求 bank 范围即可见。
    """
    from app.models.document import Document, ParentChunk
    seeded_db.add(Document(doc_id="d-gb-gen", title="GB 50000-2024 综合标准",
                           bank="standards", hs_bank="kb_general", searchable=1))
    seeded_db.add(ParentChunk(doc_id="d-gb-gen", parent_idx=0,
                              parent_text="综合标准条文" + "q" * 120))
    seeded_db.commit()

    sources = [
        {"doc": "GB 50000-2024 综合标准", "doc_id": "d-gb-gen"},        # hs_bank=kb_general
        {"doc": "GB 50174-2017 数据中心设计规范", "doc_id": "d-gb-001"},  # hs_bank=kb_standard
    ]
    # 请求 general：只放行 hs_bank=kb_general 的（与 legacy bank 列无关）
    r_gen = _assemble_standard_contents_meta(sources, bank="general")
    assert [x["doc_id"] for x in r_gen] == ["d-gb-gen"]
    # 请求 industry（范围 = kb_standard…kb_template，含 kb_general）：两者皆可见
    r_ind = _assemble_standard_contents_meta(sources, bank="industry")
    assert sorted(x["doc_id"] for x in r_ind) == ["d-gb-001", "d-gb-gen"]
    # 请求 project（范围仅 kb_project）：两者皆不可见
    r_proj = _assemble_standard_contents_meta(sources, bank="project")
    assert r_proj == []
    # bank=all：不过滤，两者皆可见
    r_all = _assemble_standard_contents_meta(sources, bank="all")
    assert sorted(x["doc_id"] for x in r_all) == ["d-gb-001", "d-gb-gen"]


def test_assemble_standard_contents_meta_empty_input(seeded_db):
    """空输入或无规范候选时返回空列表，不抛异常。"""
    assert _assemble_standard_contents_meta([], bank="all") == []
    assert _assemble_standard_contents_meta(
        [{"doc": "无标准号文档", "doc_id": "d-misc"}], bank="all"
    ) == []


def test_assemble_standard_contents_meta_missing_doc_id(seeded_db):
    """source 缺 doc_id 时被跳过，不抛异常。"""
    sources = [
        {"doc": "GB 50174-2017", "doc_id": None},
        {"doc": "", "doc_id": "d-gb-001"},
    ]
    result = _assemble_standard_contents_meta(sources, bank="all")
    assert result == []


# ═══════════════════════════════════════════════════════════════════
# _generate_query_suggestions — refined_query 不被 standard_hints 覆盖
# ═══════════════════════════════════════════════════════════════════


def test_generate_query_suggestions_rule_hit_keeps_refined_query(seeded_db):
    """P0-B fix verification: 规则匹配时 refined_query 不被 standard_hints[0] 覆盖。"""
    # "等保" 是 _keyword_suggestion_rules 中的命中词
    q = "等保测评要求"
    sources = [{"doc": "GB/T 28449-2018 等级保护测评要求", "doc_id": "d-gb-002"}]

    result = _generate_query_suggestions(q, bank="all", source_docs=sources)

    # 规则命中应产生 refined_query
    rule_refined = "等级保护测评要求包括哪些内容？"
    assert result["refined_query"] == rule_refined, (
        f"refined_query was overwritten by standard_hints[0]: {result['refined_query']!r}"
    )
    # 应该有 standard_hints
    assert len(result["standard_hints"]) >= 1
    # 应该有 follow_up_questions
    assert len(result["follow_up_questions"]) >= 3


def test_generate_query_suggestions_no_rule_falls_back_to_standard_hint(seeded_db):
    """无规则匹配时用 standard_hints[0] 作为 refined_query 兜底。"""
    q = "随便一个非规则匹配的查询"
    # 提供一个带标准号的 source
    sources = [{"doc": "GB 50174-2017 数据中心设计规范", "doc_id": "d-gb-001"}]

    result = _generate_query_suggestions(q, bank="all", source_docs=sources)

    # 没规则命中，refined_query 应来自 standard_hints
    if result["standard_hints"]:
        assert result["refined_query"] == result["standard_hints"][0]["recommended_query"]
    else:
        # 没标准号文档，refined_query 也可以是 None
        assert result["refined_query"] is None


def test_generate_query_suggestions_returns_required_keys(seeded_db):
    """返回 dict 必须含全部约定字段。"""
    result = _generate_query_suggestions("测试问题", bank="all")
    for key in ("refined_query", "term_hints", "related_docs",
                "standard_hints", "follow_up_questions"):
        assert key in result, f"missing key: {key}"
