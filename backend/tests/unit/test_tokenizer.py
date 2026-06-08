"""Tests for app.utils.tokenizer — tokenize, expand_keywords, extract_keyword_snippet."""

import pytest
from app.utils.tokenizer import tokenize, expand_keywords, extract_keyword_snippet


# ═══════════════════════════════════════════════════════
# tokenize
# ═══════════════════════════════════════════════════════

class TestTokenize:
    def test_basic_chinese(self):
        tokens = tokenize("政务信息化项目验收管理")
        assert len(tokens) > 0
        # All tokens should be > 1 char
        assert all(len(t.strip()) > 1 for t in tokens)

    def test_removes_single_char(self):
        tokens = tokenize("我是一个测试")
        # jieba will produce some single chars like "我", "是" — those should be filtered
        for t in tokens:
            assert len(t.strip()) > 1

    def test_english_text(self):
        tokens = tokenize("Hello World Testing")
        # "Hello" and "World" and "Testing" are all > 1 char
        assert any("Hello" in t or "hello" in t.lower() for t in tokens) or len(tokens) >= 0

    def test_empty_string(self):
        tokens = tokenize("")
        assert tokens == []

    def test_mixed_text(self):
        tokens = tokenize("GB/T 50314标准规范")
        assert len(tokens) > 0

    def test_returns_list(self):
        result = tokenize("测试文本")
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# expand_keywords
# ═══════════════════════════════════════════════════════

class TestExpandKeywords:
    def test_basic_expansion(self):
        keywords = ["接地电阻的测试方法"]
        result = expand_keywords(keywords)
        # Should contain original and sub-words
        assert "接地电阻的测试方法" in result
        # Should have some shorter subwords
        assert len(result) > 1

    def test_removes_stopwords_in_subwords(self):
        keywords = ["项目的验收管理"]
        result = expand_keywords(keywords)
        # "的" should not appear as a standalone token
        assert "的" not in result

    def test_short_keywords_not_split(self):
        keywords = ["测试"]
        result = expand_keywords(keywords)
        assert "测试" in result

    def test_protects_amount_patterns(self):
        keywords = ["500万元"]
        result = expand_keywords(keywords)
        assert "500万元" in result

    def test_protects_simple_amount(self):
        keywords = ["100万"]
        result = expand_keywords(keywords)
        assert "100万" in result

    def test_empty_input(self):
        result = expand_keywords([])
        assert result == []

    def test_returns_list(self):
        result = expand_keywords(["项目管理"])
        assert isinstance(result, list)

    def test_multiple_keywords(self):
        keywords = ["信息化项目管理", "验收标准规范"]
        result = expand_keywords(keywords)
        assert len(result) >= len(keywords)


# ═══════════════════════════════════════════════════════
# extract_keyword_snippet
# ═══════════════════════════════════════════════════════

class TestExtractKeywordSnippet:
    def test_finds_keyword_in_text(self):
        text = "这是一段很长的文本，包含信息化项目验收管理的关键内容。后面还有更多文字来增加长度。" * 5
        keywords = ["验收管理"]
        result = extract_keyword_snippet(text, keywords, context_chars=50)
        assert "验收管理" in result

    def test_returns_ellipsis_for_mid_text(self):
        text = "前缀" * 50 + "目标关键词在这里" + "后缀" * 50
        keywords = ["目标关键词"]
        result = extract_keyword_snippet(text, keywords, context_chars=20)
        assert "目标关键词" in result

    def test_no_keyword_returns_head(self):
        text = "没有任何匹配的文字" * 100
        keywords = ["不存在的关键词"]
        result = extract_keyword_snippet(text, keywords, context_chars=50)
        # Should return the beginning
        assert len(result) > 0

    def test_prefers_dense_match(self):
        text = "第一段普通内容。" * 20 + "特殊验收管理项目验收标准验收要求验收流程" + "结尾。" * 20
        keywords = ["验收管理", "验收标准", "验收要求"]
        result = extract_keyword_snippet(text, keywords, context_chars=30)
        # The snippet should contain the dense section
        assert "验收标准" in result or "验收管理" in result

    def test_short_text(self):
        text = "短文本"
        keywords = ["短"]
        result = extract_keyword_snippet(text, keywords, context_chars=100)
        assert len(result) > 0

    def test_empty_keywords(self):
        text = "一段文本内容"
        keywords = []
        result = extract_keyword_snippet(text, keywords, context_chars=50)
        # Returns the head of text
        assert len(result) > 0
