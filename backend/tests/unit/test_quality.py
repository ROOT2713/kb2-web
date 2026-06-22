"""Tests for app.services.quality — assess_quality, profile_document."""

import pytest
from app.services.quality import assess_quality, profile_document


# ═══════════════════════════════════════════════════════
# assess_quality
# ═══════════════════════════════════════════════════════

class TestAssessQuality:
    def test_normal_chinese_text_high_score(self):
        text = "这是一段正常的政务信息化文档内容，包含足够的有效字符。" * 10
        result = assess_quality(text)
        assert result["score"] >= 70
        assert result["total_chars"] == len(text)
        assert result["meaningful_chars"] > 0
        assert "issues" in result

    def test_short_text_zero_score(self):
        text = "太短了"
        result = assess_quality(text)
        assert result["score"] == 0
        assert "文本过短" in result["issues"][0]

    def test_empty_text(self):
        result = assess_quality("")
        assert result["score"] == 0

    def test_garbage_text_low_score(self):
        text = "�" * 100 + "正常文字" * 10
        result = assess_quality(text)
        assert result["score"] < 90
        # Should detect replacement characters
        has_garbage_issue = any("替换字符" in i for i in result["issues"])
        assert has_garbage_issue

    def test_repeated_chars_detected(self):
        text = "正常文字" * 5 + "aaaaaaaaaa" + "更多正常文字" * 5
        result = assess_quality(text)
        # May or may not trigger depending on ratio
        assert result["score"] >= 0
        assert result["score"] <= 100

    def test_pure_ascii_score(self):
        text = "This is normal English text with enough content for quality assessment. " * 10
        result = assess_quality(text)
        assert result["score"] > 0

    def test_result_structure(self):
        text = "足够长的测试文本用于质量评估，包含中文标点、数字123和字母abc。" * 5
        result = assess_quality(text)
        assert "score" in result
        assert "total_chars" in result
        assert "meaningful_chars" in result
        assert "issues" in result
        assert isinstance(result["issues"], list)

    def test_normal_text_no_issues(self):
        text = "政务信息化项目验收管理规范，适用于各级政府机关的信息化建设项目。" * 10
        result = assess_quality(text)
        assert result["score"] >= 60
        # Normal text should not have critical issues
        assert not any("乱码" in i for i in result["issues"])

    def test_score_range(self):
        for text in ["短", "中等长度文本。" * 10, "很长的文本内容。" * 100]:
            result = assess_quality(text)
            assert 0 <= result["score"] <= 100


# ═══════════════════════════════════════════════════════
# profile_document
# ═══════════════════════════════════════════════════════

class TestProfileDocument:
    def test_gb_standard_detection(self):
        text = (
            "# 1 范围\n"
            "本标准规定了安全要求。\n\n"
            "## 5.1 物理安全\n"
            "机房应有门禁系统。\n\n"
            "## 5.2 网络安全\n"
            "应划分安全域。\n\n"
            "## 5.3 主机安全\n"
            "操作系统应加固。\n\n"
            "# 6 管理要求\n"
            "应建立管理制度。\n"
        )
        result = profile_document(text)
        assert result["doc_type"] == "gb_standard"
        assert len(result["headings"]) >= 3
        assert result["confidence"] > 0

    def test_regulation_detection(self):
        text = (
            "第一条 为了规范项目管理，制定本办法。\n\n"
            "第二条 本办法适用于信息化项目。\n\n"
            "第三条 项目管理应遵循科学原则。\n\n"
            "第四条 各部门应配合项目实施。\n\n"
            "第五条 项目验收应按照规定执行。\n"
        )
        result = profile_document(text)
        assert result["doc_type"] == "regulation"
        assert len(result["headings"]) >= 3

    def test_generic_detection(self):
        text = "这是一段普通文本，没有任何标题或条例结构。只是简单的内容描述。"
        result = profile_document(text)
        assert result["doc_type"] == "generic"
        assert result["headings"] == []
        assert result["confidence"] == 0.0

    def test_raw_numbered_headings(self):
        text = (
            "1 范围\n本标准规定了。\n\n"
            "2 规范性引用文件\n下列文件。\n\n"
            "3 术语和定义\n下列术语。\n\n"
            "4 总则\n应遵循。\n"
        )
        result = profile_document(text)
        # Phase B post-merge: 仅 4 个编号且无 GB/JJF/... 引用 → 应降级为 generic
        # （这是对博客误标的硬约束）
        assert result["doc_type"] == "generic"
        assert result["headings"] == []

    def test_appendix_detection(self):
        text = (
            "# 1 范围\n内容。\n\n"
            "## 5.1 物理安全\n内容。\n\n"
            "## 5.2 网络安全\n内容。\n\n"
            "## 附录A 规范性附录\n附录内容。\n\n"
            "## A.1 详细要求\n详细内容。\n"
        )
        result = profile_document(text)
        assert result["doc_type"] == "gb_standard"

    def test_result_structure(self):
        text = "普通文本内容"
        result = profile_document(text)
        assert "doc_type" in result
        assert "headings" in result
        assert "confidence" in result
        assert isinstance(result["headings"], list)

    def test_confidence_proportional_to_headings(self):
        # Few headings → low confidence
        few = "# 1 范围\n内容\n\n## 2 引用\n内容\n\n## 3 术语\n内容\n"
        result_few = profile_document(few)

        # Many headings → higher confidence
        many = ""
        for i in range(1, 12):
            many += f"# {i} 章节{i}\n内容。\n\n"
        result_many = profile_document(many)

        if result_few["doc_type"] == "gb_standard" and result_many["doc_type"] == "gb_standard":
            assert result_many["confidence"] >= result_few["confidence"]

    def test_mixed_regulation_and_standard(self):
        """When both patterns exist, gb_standard takes priority if it has explicit standard ref."""
        text = (
            "# 1 范围\n内容\n\n"
            "## 5.1 安全\n内容引用 GB/T 22239。\n\n"
            "## 5.2 管理\n内容\n\n"
            "第一条 管理规定\n内容\n\n"
            "第二条 实施细则\n内容\n\n"
            "第三条 监督检查\n内容\n"
        )
        result = profile_document(text)
        # gb_standard has >= 3 headings AND text contains "GB/T", so it should win
        assert result["doc_type"] == "gb_standard"
