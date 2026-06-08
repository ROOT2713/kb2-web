"""Tests for app.services.generation — logic_validate (sync function)."""

import pytest
from app.services.generation import logic_validate


# ═══════════════════════════════════════════════════════
# logic_validate
# ═══════════════════════════════════════════════════════

class TestLogicValidate:
    """Test the synchronous logic_validate function."""

    def test_no_issues_clean_text(self):
        answer = "根据文档要求，项目应在规定时间内完成验收。"
        context = "根据文档要求，项目应在规定时间内完成验收。"
        result = logic_validate(answer, context, sources=[])
        assert result["score"] == 100
        assert len(result["issues"]) == 0

    def test_number_mismatch_high_severity(self):
        answer = "项目预算为5000万元，工期180天。"
        context = "项目预算为3000万元。"
        result = logic_validate(answer, context, sources=[])
        # 5000 is meaningful (>= 100, not a year, not round 100)
        issues = [i for i in result["issues"] if i["type"] == "number_mismatch"]
        assert len(issues) > 0
        assert issues[0]["severity"] == "high"
        assert result["score"] < 100

    def test_number_mismatch_ignores_small_numbers(self):
        answer = "需要3台服务器。"
        context = "需要5台服务器。"
        result = logic_validate(answer, context, sources=[])
        # 3 and 5 are < 100, should be ignored
        num_issues = [i for i in result["issues"] if i["type"] == "number_mismatch"]
        assert len(num_issues) == 0

    def test_number_mismatch_ignores_years(self):
        answer = "2024年发布的标准。"
        context = "2023年发布的标准。"
        result = logic_validate(answer, context, sources=[])
        # Years (1990-2030) should be ignored
        num_issues = [i for i in result["issues"] if i["type"] == "number_mismatch"]
        assert len(num_issues) == 0

    def test_number_mismatch_ignores_round_hundreds(self):
        answer = "投资500万元。"
        context = "投资300万元。"
        result = logic_validate(answer, context, sources=[])
        # 500 and 300 are divisible by 100, should be ignored by is_meaningful
        num_issues = [i for i in result["issues"] if i["type"] == "number_mismatch"]
        assert len(num_issues) == 0

    def test_standard_mismatch_critical(self):
        answer = "应符合GB/T 50314-2015标准要求。"
        context = "应符合GB/T 22239-2019标准要求。"
        result = logic_validate(answer, context, sources=[])
        std_issues = [i for i in result["issues"] if i["type"] == "standard_mismatch"]
        assert len(std_issues) > 0
        assert std_issues[0]["severity"] == "critical"
        assert result["score"] <= 70  # 100 - 30 = 70

    def test_standard_no_mismatch(self):
        answer = "应符合GB/T 50314-2015标准。"
        context = "本项目应符合GB/T 50314-2015标准要求。"
        result = logic_validate(answer, context, sources=[])
        std_issues = [i for i in result["issues"] if i["type"] == "standard_mismatch"]
        assert len(std_issues) == 0

    def test_condition_escalation_medium(self):
        answer = "必须建立完善的安全管理制度。"
        context = "建议建立安全管理制度。"
        result = logic_validate(answer, context, sources=[])
        cond_issues = [i for i in result["issues"] if i["type"] == "condition_escalation"]
        assert len(cond_issues) > 0
        assert cond_issues[0]["severity"] == "medium"

    def test_condition_escalation_should_word(self):
        answer = "应当定期进行安全检查。"
        context = "建议定期进行安全检查。"
        result = logic_validate(answer, context, sources=[])
        cond_issues = [i for i in result["issues"] if i["type"] == "condition_escalation"]
        assert len(cond_issues) > 0

    def test_no_escalation_when_context_has_must(self):
        answer = "必须执行安全策略。"
        context = "要求必须执行安全策略。"
        result = logic_validate(answer, context, sources=[])
        cond_issues = [i for i in result["issues"] if i["type"] == "condition_escalation"]
        assert len(cond_issues) == 0

    def test_no_escalation_when_context_has_yingdang(self):
        answer = "应当完成验收。"
        context = "应当完成验收工作。"
        result = logic_validate(answer, context, sources=[])
        cond_issues = [i for i in result["issues"] if i["type"] == "condition_escalation"]
        assert len(cond_issues) == 0

    def test_multiple_issues_cumulative_score(self):
        answer = "必须按照GB/T 50314-2015标准执行，预算5000万元。"
        context = "建议按照GB/T 22239-2019标准参考，预算3000万元。"
        result = logic_validate(answer, context, sources=[])
        # Should have: number_mismatch (-15) + standard_mismatch (-30) + condition_escalation (-5)
        assert len(result["issues"]) >= 2
        assert result["score"] < 100

    def test_score_never_negative(self):
        # Create scenario with many issues
        answer = "必须按照GB/T 50314、GB/T 22239、GB/T 28448标准，投资9999万元、工期777天。"
        context = "建议参考。"
        result = logic_validate(answer, context, sources=[])
        assert result["score"] >= 0

    def test_result_structure(self):
        result = logic_validate("答案", "上下文", sources=[])
        assert "issues" in result
        assert "score" in result
        assert isinstance(result["issues"], list)
        assert isinstance(result["score"], int)

    def test_issue_structure(self):
        answer = "必须执行。"
        context = "建议执行。"
        result = logic_validate(answer, context, sources=[])
        if result["issues"]:
            issue = result["issues"][0]
            assert "type" in issue
            assert "severity" in issue
            assert "detail" in issue
            assert "fix" in issue

    def test_empty_inputs(self):
        result = logic_validate("", "", sources=[])
        assert result["score"] == 100
        assert len(result["issues"]) == 0

    def test_meaningful_number_with_decimal(self):
        answer = "评分为3.85分。"
        context = "评分为4.20分。"
        result = logic_validate(answer, context, sources=[])
        # 3.85 and 4.20 are < 100, should be ignored
        num_issues = [i for i in result["issues"] if i["type"] == "number_mismatch"]
        assert len(num_issues) == 0
