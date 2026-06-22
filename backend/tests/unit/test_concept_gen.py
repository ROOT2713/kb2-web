"""Tests for app.services.concept_gen — infer_doc_concept_id, generate_concepts_for_doc."""

import pytest
from app.services.concept_gen import (
    infer_doc_concept_id,
    _title_to_slug,
    _infer_subdomain,
    _extract_section_title,
    _generate_concept_id,
)


# ═══════════════════════════════════════════════════════
# infer_doc_concept_id
# ═══════════════════════════════════════════════════════

class TestInferDocConceptId:
    def test_gb_standard_with_number(self):
        """GB 标准号提取: GB/T 50116-2013 → standards/security/gb-t-50116-2013"""
        result = infer_doc_concept_id(
            title="GB/T 50116-2013 火灾自动报警系统设计规范",
            bank="standard",
            doc_type="gb_standard",
        )
        assert result is not None
        assert result.startswith("standards/")
        assert "gb" in result
        assert "50116" in result

    def test_gb_standard_no_number(self):
        """无标准号的 GB 标准 → 用标题 slug"""
        result = infer_doc_concept_id(
            title="某标准文档",
            bank="standard",
            doc_type="gb_standard",
        )
        assert result is not None
        assert result.startswith("standards/")
        assert "某标准文档" in result

    def test_regulation(self):
        """法规文档 → standards/{subdomain}/{slug}"""
        result = infer_doc_concept_id(
            title="网络安全法",
            bank="law",
            doc_type="regulation",
        )
        assert result is not None
        assert result.startswith("standards/")
        assert "网络安全" in result

    def test_generic_document(self):
        """通用文档 → methodology/{slug}"""
        result = infer_doc_concept_id(
            title="AI 应用实践指南",
            bank="general",
            doc_type="generic",
        )
        assert result is not None
        assert result.startswith("methodology/")
        assert "ai" in result

    def test_empty_title_returns_none(self):
        """空标题 → None"""
        result = infer_doc_concept_id(title="", bank="general")
        assert result is None

    def test_subdomain_inference_security(self):
        """安全相关文档 → subdomain=security"""
        result = infer_doc_concept_id(
            title="信息系统安全等级保护",
            bank="standard",
            doc_type="gb_standard",
            text="网络安全 消防 安防",
        )
        assert result is not None
        assert "security" in result

    def test_subdomain_inference_laboratory(self):
        """实验室相关文档 → subdomain=laboratory"""
        result = infer_doc_concept_id(
            title="实验室检测方法",
            bank="standard",
            doc_type="gb_standard",
            text="检测 检验 校准",
        )
        assert result is not None
        assert "laboratory" in result


# ═══════════════════════════════════════════════════════
# _title_to_slug
# ═══════════════════════════════════════════════════════

class TestTitleToSlug:
    def test_chinese_title(self):
        slug = _title_to_slug("网络安全法实施细则")
        assert slug == "网络安全法实施细则"

    def test_mixed_title(self):
        slug = _title_to_slug("GB/T 50116 火灾报警")
        assert "gb" in slug
        assert "火灾报警" in slug

    def test_empty_title(self):
        slug = _title_to_slug("")
        assert slug == ""

    def test_special_chars_cleaned(self):
        slug = _title_to_slug("Hello! World? @#$")
        assert "!" not in slug
        assert "?" not in slug


# ═══════════════════════════════════════════════════════
# _infer_subdomain
# ═══════════════════════════════════════════════════════

class TestInferSubdomain:
    def test_security_keywords(self):
        assert _infer_subdomain("安全") == "security"
        assert _infer_subdomain("消防系统") == "security"

    def test_laboratory_keywords(self):
        assert _infer_subdomain("实验室检测") == "laboratory"
        assert _infer_subdomain("校准方法") == "laboratory"

    def test_quality_keywords(self):
        assert _infer_subdomain("质量管理体系") == "quality"

    def test_no_match(self):
        assert _infer_subdomain("人工智能概述") == ""


# ═══════════════════════════════════════════════════════
# _extract_section_title
# ═══════════════════════════════════════════════════════

class TestExtractSectionTitle:
    def test_markdown_heading(self):
        assert _extract_section_title("## 4 总则\n内容") == "4 总则"

    def test_chapter_marker(self):
        assert _extract_section_title("第三章 网络安全\n内容").startswith("第三章")

    def test_gb_clause(self):
        assert _extract_section_title("4.1.2 术语和定义\n内容").startswith("4.1.2")

    def test_fallback(self):
        result = _extract_section_title("这是一段普通文本内容")
        assert len(result) <= 80


# ═══════════════════════════════════════════════════════
# _generate_concept_id
# ═══════════════════════════════════════════════════════

class TestGenerateConceptId:
    def test_with_doc_concept_id(self):
        """新版格式: {concept_id}/{doc_id-short}/section-{idx}-{slug}"""
        cid = _generate_concept_id("standards/gb-50116", 0, "总则", "doc-abc-123")
        assert "standards/gb-50116/" in cid
        assert "doc-abc-" in cid
        assert "section-0-" in cid
        assert "总则" in cid

    def test_without_doc_concept_id(self):
        """无 concept_id 时用 unknown"""
        cid = _generate_concept_id(None, 3, "范围", "doc-xyz-456")
        assert "unknown/" in cid
        assert "doc-xyz-" in cid
        assert "section-3-" in cid
        assert "范围" in cid

    def test_long_title_truncated(self):
        long_title = "这是一个非常非常长的标题" * 10
        cid = _generate_concept_id("base", 0, long_title, "doc-001")
        # slug 部分应该被截断到 40 字符
        parts = cid.split("/section-0-")
        assert len(parts[1]) <= 40

    def test_no_doc_id_uses_unknown(self):
        """不传 doc_id 时用 unknown 命名空间"""
        cid = _generate_concept_id("base", 0, "测试", "")
        assert "/unknown/" in cid
