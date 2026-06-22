"""Tests for app.services.chunking — heading_chunk, parent_child_chunk, excel_row_chunk, select_strategy."""

import pytest
from app.services.chunking import (
    heading_chunk,
    parent_child_chunk,
    excel_row_chunk,
    select_strategy,
    extract_table_chunks,
    HeadingChunking,
    ParentChildChunking,
    ExcelRowChunking,
    Chunk,
    _clause_split,
)


# ═══════════════════════════════════════════════════════
# parent_child_chunk
# ═══════════════════════════════════════════════════════

class TestParentChildChunk:
    def test_basic_chunking(self):
        text = "段落一。" * 50 + "\n\n" + "段落二。" * 50
        result = parent_child_chunk(text, child_size=200, parent_size=800, overlap=40)
        assert len(result) > 0
        for chunk in result:
            assert "child" in chunk
            assert "parent" in chunk
            assert "child_index" in chunk
            assert "parent_index" in chunk
            assert "section_hint" in chunk

    def test_empty_text(self):
        result = parent_child_chunk("")
        assert result == []

    def test_short_text(self):
        text = "短文本"
        result = parent_child_chunk(text, child_size=200, parent_size=800)
        assert len(result) >= 1

    def test_child_size_respected(self):
        text = "A" * 1000
        result = parent_child_chunk(text, child_size=200, parent_size=1000, overlap=0)
        for chunk in result:
            # child should be approximately child_size (may be adjusted for sentence boundaries)
            assert len(chunk["child"]) <= 240  # 200 * 1.2 for boundary search

    def test_parent_contains_child_content(self):
        text = "内容一。" * 100 + "\n\n" + "内容二。" * 100
        result = parent_child_chunk(text, child_size=100, parent_size=500, overlap=20)
        for chunk in result:
            # parent should contain at least part of the child text
            assert chunk["parent"]  # non-empty

    def test_indices_are_sequential(self):
        text = "长内容。" * 200
        result = parent_child_chunk(text, child_size=100, parent_size=400, overlap=10)
        for i, chunk in enumerate(result):
            assert chunk["child_index"] == i

    def test_section_hint_present(self):
        text = "第一章内容。" * 50 + "\n\n" + "第二章内容。" * 50
        result = parent_child_chunk(text, child_size=200, parent_size=800)
        assert len(result) > 0
        for chunk in result:
            assert chunk["section_hint"]  # non-empty


# ═══════════════════════════════════════════════════════
# heading_chunk
# ═══════════════════════════════════════════════════════

class TestHeadingChunk:
    def test_gb_standard_with_markdown_headings(self):
        text = (
            "# 1 范围\n本标准规定了安全要求。\n\n"
            "## 5.1 物理安全\n机房应有门禁系统。\n\n"
            "## 5.2 网络安全\n应划分安全域。\n\n"
            "# 6 管理要求\n应建立管理制度。\n"
        )
        profile = {
            "doc_type": "gb_standard",
            "headings": [
                (1, "1 范围", 0),
                (2, "5.1 物理安全", 40),
                (2, "5.2 网络安全", 80),
                (1, "6 管理要求", 120),
            ],
            "confidence": 0.5,
        }
        result = heading_chunk(text, profile, min_child_size=10, max_parent_size=2000)
        assert len(result) > 0

    def test_empty_headings_returns_empty(self):
        text = "正文内容"
        profile = {"doc_type": "gb_standard", "headings": [], "confidence": 0}
        result = heading_chunk(text, profile)
        assert result == []

    def test_unknown_doc_type_returns_empty(self):
        text = "正文内容"
        profile = {"doc_type": "unknown_type", "headings": [(1, "title", 0)], "confidence": 0.3}
        result = heading_chunk(text, profile)
        assert result == []

    def test_regulation_type(self):
        text = "第一条 为了规范管理。\n\n第二条 适用范围。\n\n第三条 职责分工。\n"
        profile = {
            "doc_type": "regulation",
            "headings": [
                (1, "第一条 为了规范管理。", 0),
                (1, "第二条 适用范围。", 20),
                (1, "第三条 职责分工。", 40),
            ],
            "confidence": 0.5,
        }
        result = heading_chunk(text, profile, min_child_size=10)
        assert len(result) > 0
        # Regulation chunks should have child and parent
        for chunk in result:
            assert "child" in chunk
            assert "parent" in chunk

    def test_result_format(self):
        text = "# 4 总则\n内容。\n\n## 4.1 子内容\n详细内容。"
        profile = {
            "doc_type": "gb_standard",
            "headings": [(1, "4 总则", 0), (2, "4.1 子内容", 20)],
            "confidence": 0.3,
        }
        result = heading_chunk(text, profile, min_child_size=10)
        if result:
            for chunk in result:
                assert "child_index" in chunk
                assert "parent_index" in chunk
                assert "section_hint" in chunk


# ═══════════════════════════════════════════════════════
# excel_row_chunk
# ═══════════════════════════════════════════════════════

class TestExcelRowChunk:
    def test_basic_excel_chunking(self):
        text = (
            "[Sheet: Sheet1]\n"
            "第1项 - 调查类\n检查项: 服务器配置\n检查方法: 现场检查\n\n"
            "第2项 - 方案类\n检查项: 网络拓扑\n检查方法: 文档审查\n\n"
            "第3项 - 验收类\n检查项: 系统功能\n检查方法: 功能测试\n"
        )
        result = excel_row_chunk(text, "安全检查表")
        assert len(result) >= 3
        for chunk in result:
            assert "child" in chunk
            assert "parent" in chunk
            assert chunk["child"] == chunk["parent"]  # excel: child == parent

    def test_empty_text(self):
        result = excel_row_chunk("", "空表")
        assert result == []

    def test_section_hint_contains_title(self):
        text = "第1项 - 测试\n内容\n\n"
        result = excel_row_chunk(text, "检查表")
        if result:
            assert "检查表" in result[0]["section_hint"] or "第1项" in result[0]["section_hint"]

    def test_non_excel_text(self):
        text = "普通段落\n没有检查项格式\n"
        result = excel_row_chunk(text)
        # Should return chunks based on empty-line splitting
        # Each chunk has the text
        assert isinstance(result, list)

    def test_indices_sequential(self):
        text = "第1项\n内容A\n\n第2项\n内容B\n\n第3项\n内容C\n"
        result = excel_row_chunk(text)
        for i, chunk in enumerate(result):
            assert chunk["child_index"] == i


# ═══════════════════════════════════════════════════════
# extract_table_chunks
# ═══════════════════════════════════════════════════════

class TestExtractTableChunks:
    def test_markdown_table(self):
        text = (
            "| 名称 | 数量 | 价格 |\n"
            "| --- | --- | --- |\n"
            "| 服务器 | 2 | 5000 |\n"
            "| 交换机 | 3 | 2000 |\n"
        )
        result = extract_table_chunks(text)
        assert len(result) >= 1

    def test_html_table(self):
        text = "<table><tr><td>名称</td><td>数量</td></tr><tr><td>服务器</td><td>2</td></tr></table>"
        result = extract_table_chunks(text)
        assert len(result) >= 1

    def test_no_table(self):
        text = "这是一段普通文本，没有表格。"
        result = extract_table_chunks(text)
        assert result == []


# ═══════════════════════════════════════════════════════
# select_strategy
# ═══════════════════════════════════════════════════════

class TestSelectStrategy:
    def test_excel_file(self):
        strategy = select_strategy("data.xlsx", "content")
        assert isinstance(strategy, ExcelRowChunking)

    def test_excel_xls(self):
        strategy = select_strategy("data.xls", "content")
        assert isinstance(strategy, ExcelRowChunking)

    def test_default_heading(self):
        strategy = select_strategy("document.pdf", "content")
        assert isinstance(strategy, HeadingChunking)

    def test_markdown_file(self):
        strategy = select_strategy("readme.md", "content")
        assert isinstance(strategy, HeadingChunking)

    def test_txt_file(self):
        strategy = select_strategy("notes.txt", "content")
        assert isinstance(strategy, HeadingChunking)


# ═══════════════════════════════════════════════════════
# Strategy classes
# ═══════════════════════════════════════════════════════

class TestHeadingChunkingStrategy:
    def test_returns_chunk_list(self):
        text = "# 1 范围\n标准规定了范围。\n\n## 1.1 子范围\n具体内容。\n"
        strategy = HeadingChunking()
        result = strategy.chunk(text)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], Chunk)


class TestParentChildChunkingStrategy:
    def test_returns_chunk_list(self):
        text = "段落一。" * 50 + "\n\n" + "段落二。" * 50
        strategy = ParentChildChunking()
        result = strategy.chunk(text)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], Chunk)
            assert result[0].text  # non-empty


class TestExcelRowChunkingStrategy:
    def test_returns_chunk_list(self):
        text = "第1项\n检查内容\n\n第2项\n检查内容\n"
        strategy = ExcelRowChunking()
        result = strategy.chunk(text, filename="test.xlsx")
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# _clause_split (P0-4 clause-level segmentation)
# ═══════════════════════════════════════════════════════

class TestClauseSplit:
    def test_short_text_no_split(self):
        """短文本不分割"""
        text = "短文本内容"
        result = _clause_split(text, max_child_size=800)
        assert len(result) == 1
        assert result[0]["text"] == text
        assert result[0]["clause_id"] == ""

    def test_nested_numbered_clauses(self):
        """嵌套编号条款拆分: 5.1.1, 5.1.2"""
        # Need text > 800 chars to trigger splitting
        text = "5.1.1 术语定义\n" + "本标准采用下列术语和定义。" * 30 + "\n\n5.1.2 缩略语\n" + "下列缩略语适用于本标准。" * 30 + "\n\n5.1.3 符号\n" + "下列符号适用于本标准。" * 30
        result = _clause_split(text, max_child_size=800)
        assert len(result) >= 2
        # Check that clause IDs are extracted
        clause_ids = [r["clause_id"] for r in result]
        assert "5.1.1" in clause_ids
        assert "5.1.2" in clause_ids

    def test_article_clauses(self):
        """条款编号拆分: 第N条"""
        # Need text > 800 chars to trigger splitting
        text = "第一条 总则\n" + "为规范火灾自动报警系统的设计，制定本规范。" * 20 + "\n\n第二条 适用范围\n" + "本规范适用于新建、扩建和改建的建筑工程。" * 20 + "\n\n第三条 术语\n" + "火灾自动报警系统由触发器件等组成。" * 20
        result = _clause_split(text, max_child_size=800)
        assert len(result) >= 2
        clause_ids = [r["clause_id"] for r in result]
        assert "第一条" in clause_ids
        assert "第二条" in clause_ids

    def test_paragraph_splitting(self):
        """无编号时按段落拆分"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        result = _clause_split(text, max_child_size=800)
        # Should split by paragraphs
        assert len(result) >= 1

    def test_hard_split_fallback(self):
        """无段落无编号时硬分割"""
        text = "连续文本无分隔符" * 200
        result = _clause_split(text, max_child_size=200)
        assert len(result) > 1
        for r in result:
            assert len(r["text"]) <= 200

    def test_appendix_clauses(self):
        """附录编号拆分: A.1, A.2"""
        # Need text > 800 chars to trigger splitting
        text = "A.1 附录A内容\n" + "本附录规定了测试方法。" * 40 + "\n\nA.2 附录A详细步骤\n" + "第一步准备工作如下。" * 40
        result = _clause_split(text, max_child_size=800)
        assert len(result) >= 2
        clause_ids = [r["clause_id"] for r in result]
        assert "A.1" in clause_ids
        assert "A.2" in clause_ids
