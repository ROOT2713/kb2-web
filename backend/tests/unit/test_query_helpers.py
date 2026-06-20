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
        Document(doc_id="d-gb-001", title="GB 50174-2017 数据中心设计规范",
                 bank="standards", searchable=1),
        Document(doc_id="d-gb-002", title="GB/T 28449-2018 等级保护测评要求",
                 bank="standards", searchable=1),
        Document(doc_id="d-misc",   title="小红书笔记示例",  # 不匹配 _STD_PATTERN
                 bank="general", searchable=1),
        Document(doc_id="d-disabled", title="GB 50116-2013 火警规范",
                 bank="standards", searchable=0),  # searchable=0 应被排除
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

    # Repoint SessionLocal to test session factory
    import app.api.query as q_mod
    monkeypatch.setattr(q_mod, "SessionLocal", lambda: db_session)
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
    """bank=general 时不应返回 standards 文档。"""
    sources = [
        {"doc": "GB 50174-2017 数据中心设计规范", "doc_id": "d-gb-001"},  # standards bank
    ]
    result = _assemble_standard_contents_meta(sources, bank="general")
    assert result == []


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
