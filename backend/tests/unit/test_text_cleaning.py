"""Tests for app.utils.text_cleaning — all public functions."""

import pytest
from app.utils.text_cleaning import (
    clean_watermarks,
    clean_pipeline,
    normalize_query,
    normalize_standard_numbers,
    expand_amount_tiers,
    filename_to_title,
    deai_postprocess,
    clean_page_artifacts,
    clean_html_residuals,
    clean_encoding_errors,
    normalize_whitespace,
    clean_transcript_errors,
    _extract_numbers,
    _fix_encoding,
)


# ═══════════════════════════════════════════════════════
# clean_watermarks
# ═══════════════════════════════════════════════════════

class TestCleanWatermarks:
    def test_removes_repeated_watermark_lines(self):
        text = "正常内容\nwww.bzfxw.com\nwww.bzfxw.com\nwww.bzfxw.com\n更多内容"
        result = clean_watermarks(text)
        assert "bzfxw" not in result
        assert "正常内容" in result

    def test_removes_single_watermark_line(self):
        text = "第一行\nwww.example.com\n第三行"
        result = clean_watermarks(text)
        assert "example.com" not in result
        assert "第一行" in result

    def test_removes_garbled_watermark_pattern(self):
        text = "前文[fQTQT www.bzfxw.com hQ]后文"
        result = clean_watermarks(text)
        assert "fQTQT" not in result
        assert "bzfxw" not in result

    def test_removes_copyright_text(self):
        text = "文档内容版权所有，翻印必究"
        result = clean_watermarks(text)
        assert "版权所有" not in result
        assert "翻印必究" not in result

    def test_removes_confidential_notice(self):
        text = "正文内容\n内部资料 请勿外传泄露"
        result = clean_watermarks(text)
        assert "请勿" not in result or "内部资料" not in result

    def test_removes_disclaimer(self):
        text = "免责声明：不代表本单位观点"
        result = clean_watermarks(text)
        assert "不代表" not in result or "免责声明" not in result

    def test_collapses_excessive_blank_lines(self):
        text = "A\n\n\n\n\nB"
        result = clean_watermarks(text)
        assert "\n\n\n" not in result
        assert "A" in result
        assert "B" in result

    def test_no_change_on_clean_text(self):
        text = "这是一段正常文本。"
        result = clean_watermarks(text)
        assert result == text

    def test_empty_input(self):
        assert clean_watermarks("") == ""


# ═══════════════════════════════════════════════════════
# clean_page_artifacts
# ═══════════════════════════════════════════════════════

class TestCleanPageArtifacts:
    def test_removes_chinese_page_number(self):
        text = "内容\n第 3 页 / 共 10 页\n更多内容"
        result = clean_page_artifacts(text)
        assert "第" not in result or "页" not in result

    def test_removes_english_page_number(self):
        text = "content\nPage 5 of 20\nmore"
        result = clean_page_artifacts(text)
        assert "Page 5" not in result

    def test_removes_dash_page_line(self):
        text = "text\n— 7 —\nmore"
        result = clean_page_artifacts(text)
        assert "— 7 —" not in result


# ═══════════════════════════════════════════════════════
# clean_html_residuals
# ═══════════════════════════════════════════════════════

class TestCleanHtmlResiduals:
    def test_removes_html_tags(self):
        text = "before<div class='x'>content</div>after"
        result = clean_html_residuals(text)
        assert "<div" not in result
        assert "content" in result

    def test_converts_br_to_newline(self):
        text = "line1<br/>line2"
        result = clean_html_residuals(text)
        assert "\n" in result

    def test_removes_style_attributes(self):
        text = '<p style="color:red">text</p>'
        result = clean_html_residuals(text)
        assert "style=" not in result

    def test_stray_angle_bracket_does_not_eat_following_text(self):
        """OCR 讹字里的落单 '<a'（如 '<ACS)'）不得跨段吞并正文。

        回归：旧正则 `</?(div|span|p|table|tr|td|th|img|a)[^>]*>` 的 `[^>]*`
        可跨换行——线上 GB 50348-2018 文本因 'access control system<ACS)' 一次
        被删 44,320 字符（含第 6.4.5 条正文）。
        """
        filler = "正文内容甲。" * 3000  # 18,000 字符夹在中间
        text = "access control system<ACS)\n" + filler + "\n:>"
        result = clean_html_residuals(text)
        assert "正文内容甲。" in result, "落单 '<a' 吞掉了中间正文"
        assert len(result) >= len(filler)

    def test_plain_tags_still_stripped(self):
        """收紧边界后，合法标签仍必须被移除。"""
        for t in ["<div class='x'>内容</div>", "<p>段落</p>", "</span>",
                  "<td colspan=2>", "<a href='#'>链接</a>"]:
            r = clean_html_residuals(t)
            assert "<" not in r and ">" not in r, f"{t!r} -> {r!r}"

    def test_pipeline_preserves_text_around_stray_bracket(self):
        """端到端：clean_pipeline 不得因落单 '<a' 丢正文。"""
        filler = "条款正文内容乙。" * 2000
        result = clean_pipeline("模式识别系统<ACS)\n" + filler + "\n:>结束")
        assert "条款正文内容乙。" in result

    def test_runaway_attribute_span_not_swallowed(self):
        """属性段限长 2000：'<a ' 后隔 ~5000 字符才有 '>' 时不得吞掉中间正文。

        突变把 `[^>]{0,2000}` 改回 `[^>]*` → 本用例变红。
        """
        text = "前缀 <a " + ("正文丁。" * 1500) + " > 后缀"  # 跨度 > 5000 字符
        result = clean_html_residuals(text)
        assert "正文丁。" in result, "无限的属性段吞掉了中间正文"

    def test_non_tag_sequences_preserved(self):
        """标签名后不是合法边界（如 '<divx>'、'<p3>'）时不得当标签删除。

        突变去掉 `(?=[\\s/>])` 前瞻 → 本用例变红（限长兜不住这种短跨度）。
        """
        for s in ["<divx>", "<p3>", "<td2>"]:
            assert s in clean_html_residuals(s), f"{s!r} 被误当标签删除"

    def test_oversized_tag_not_deleted(self):
        """超长伪标签（字符级硬限 1000）须原样保留，防整段正文被当属性删除。

        复算 CC 的 PoC：'<a "' + 10 万字符 + '">' 曾被整段删除（100,006 字符）。
        """
        body = "正文戊。" * 20000  # 80,000 字符
        t = '前文<a "' + body + '">后文'
        r = clean_html_residuals(t)
        assert "正文戊。" in r, "超长伪标签吞掉了正文"
        assert len(r) >= len(body)

    def test_normal_tag_still_stripped_under_cap(self):
        """硬限内的正常标签仍须剥离（语料实测最长 28 字符）。"""
        t = '<td colspan="1" rowspan="1">内容</td>'
        r = clean_html_residuals(t)
        assert "<td" not in r and "内容" in r

    def test_gt_inside_quoted_attribute(self):
        """属性值内含 '>' 时须匹配到标签真正的结尾（引用感知），不得提前结束。"""
        t = '<a title="x > y">链接</a>'
        r = clean_html_residuals(t)
        assert r == "链接", f"引用感知失效，残留 {r!r}"

    def test_table_lookalike_not_converted(self):
        """'<tableABC' 类伪标签不得触发表格转换（边界前瞻）。"""
        r = clean_html_residuals("前<tableABC>中</table>后")
        assert "前" in r and "中" in r and "后" in r


# ═══════════════════════════════════════════════════════
# clean_encoding_errors
# ═══════════════════════════════════════════════════════

class TestCleanEncodingErrors:
    def test_removes_replacement_char(self):
        text = "正常�字符"
        result = clean_encoding_errors(text)
        assert "�" not in result

    def test_removes_bom(self):
        text = "\ufeff开头"
        result = clean_encoding_errors(text)
        assert "\ufeff" not in result

    def test_removes_zero_width_chars(self):
        text = "零\u200b宽\u200c字\u200d符"
        result = clean_encoding_errors(text)
        assert "\u200b" not in result


# ═══════════════════════════════════════════════════════
# normalize_whitespace
# ═══════════════════════════════════════════════════════

class TestNormalizeWhitespace:
    def test_fullwidth_to_halfwidth(self):
        text = "ＡＢＣ１２３"
        result = normalize_whitespace(text)
        assert result == "ABC123"

    def test_fullwidth_space(self):
        text = "Ａ\u3000Ｂ"
        result = normalize_whitespace(text)
        assert "\u3000" not in result

    def test_collapses_multiple_spaces(self):
        text = "a  b   c"
        result = normalize_whitespace(text)
        assert "  " not in result


# ═══════════════════════════════════════════════════════
# clean_transcript_errors
# ═══════════════════════════════════════════════════════

class TestCleanTranscriptErrors:
    def test_removes_filler_words(self):
        text = "。嗯 方案啊不错"
        result = clean_transcript_errors(text)
        assert "嗯" not in result
        assert "方案" in result

    def test_preserves_context(self):
        text = "关于技术方案的讨论"
        result = clean_transcript_errors(text)
        assert "技术方案" in result


# ═══════════════════════════════════════════════════════
# clean_pipeline
# ═══════════════════════════════════════════════════════

class TestCleanPipeline:
    def test_full_pipeline_basic(self):
        text = "正常内容\n\n\n\n第 1 页 / 共 5 页\n\n\n\n版权所有"
        result = clean_pipeline(text)
        assert "正常内容" in result
        assert "\n\n\n" not in result

    def test_pipeline_with_video_hint(self):
        text = "。嗯 方案啊不错"
        result = clean_pipeline(text, source_hint="video")
        assert "嗯" not in result

    def test_pipeline_strips_whitespace(self):
        text = "  \n  text  \n  "
        result = clean_pipeline(text)
        assert result == "text"

    def test_pipeline_cleans_html_and_watermarks(self):
        text = "<div>内容</div>\nwww.test.com\nwww.test.com\nwww.test.com"
        result = clean_pipeline(text)
        assert "<div" not in result
        assert "test.com" not in result

    def test_pipeline_watchdog_warns_on_massive_shrink(self, caplog):
        """清洗后字符骤降（<80%）须告警，便于发现静默丢内容。"""
        import logging
        text = "正文内容。" * 2000  # 10,000 字符
        with caplog.at_level(logging.WARNING, logger="app.utils.text_cleaning"):
            # 注入一个会触发大幅删除的输入：落单 '<a' 本不该删，但为验证看门狗，
            # 直接构造一个确实会被清洗掉大段的场景（海量水印行）。
            shrink = "内容X。" * 1000 + "\n" + ("www.a.com\n" * 2000)
            clean_pipeline(shrink)
        assert any("降幅异常" in r.message or "降幅异常" in r.getMessage() for r in caplog.records), \
            "看门狗未告警"


# ═══════════════════════════════════════════════════════
# normalize_query
# ═══════════════════════════════════════════════════════

class TestNormalizeQuery:
    def test_basic_lower_and_strip(self):
        assert normalize_query("  Hello World  ") == "hello world"

    def test_collapse_spaces(self):
        assert normalize_query("  多   个   空格  ") == "多 个 空格"

    def test_chinese_text(self):
        result = normalize_query("  项目 验收  ")
        assert result == "项目 验收"

    def test_empty_string(self):
        assert normalize_query("") == ""


# ═══════════════════════════════════════════════════════
# normalize_standard_numbers
# ═══════════════════════════════════════════════════════

class TestNormalizeStandardNumbers:
    def test_unicode_slash_to_ascii(self):
        result = normalize_standard_numbers("GB∕T 50314")
        assert "∕" not in result
        assert "/" in result

    def test_dash_normalization(self):
        result = normalize_standard_numbers("GB—50314")
        assert "—" not in result
        assert "-" in result

    def test_adds_space_after_t(self):
        result = normalize_standard_numbers("GA/T669")
        assert "GA/T 669" in result

    def test_removes_extra_space_before_t(self):
        result = normalize_standard_numbers("GA /T 669")
        assert "GA/T" in result

    def test_prefix_number_spacing(self):
        result = normalize_standard_numbers("GA1383")
        assert "GA 1383" in result

    def test_no_change_clean_format(self):
        result = normalize_standard_numbers("GB/T 50314-2015")
        assert "GB/T 50314-2015" in result


# ═══════════════════════════════════════════════════════
# expand_amount_tiers
# ═══════════════════════════════════════════════════════

class TestExpandAmountTiers:
    def test_small_amount_50万(self):
        result = expand_amount_tiers("50万软件项目")
        assert "100万以下" in result

    def test_medium_amount_200万(self):
        result = expand_amount_tiers("200万项目")
        assert "100万" in result

    def test_large_amount_500万(self):
        result = expand_amount_tiers("500万元系统集成")
        assert "300万元以上" in result

    def test_very_large_amount_2000万(self):
        result = expand_amount_tiers("2000万项目")
        assert "1000万以上" in result

    def test_no_amount_unchanged(self):
        result = expand_amount_tiers("普通查询")
        assert result == "普通查询"

    def test_preserves_original_query(self):
        result = expand_amount_tiers("500万项目")
        assert result.startswith("500万项目")

    def test_supports_万元_unit(self):
        result = expand_amount_tiers("100万元")
        assert "100万" in result


# ═══════════════════════════════════════════════════════
# filename_to_title
# ═══════════════════════════════════════════════════════

class TestFilenameToTitle:
    def test_extracts_heading_from_content(self):
        content = "# 第一章 总则\n\n正文内容"
        result = filename_to_title("doc.pdf", content)
        assert result == "第一章 总则"

    def test_extracts_h2_heading(self):
        content = "一些内容\n## 5.1 安全要求\n正文"
        result = filename_to_title("doc.pdf", content)
        assert result == "5.1 安全要求"

    def test_falls_back_to_stem(self):
        result = filename_to_title("项目验收报告.pdf")
        assert result == "项目验收报告"

    def test_empty_content_uses_stem(self):
        result = filename_to_title("test.docx", "")
        assert result == "test"

    def test_no_heading_in_content(self):
        content = "这是一段没有标题的正文\n第二行"
        result = filename_to_title("doc.pdf", content)
        assert result == "doc"

    def test_skips_generic_standard_heading(self):
        content = "# 中华人民共和国国家标准\n\n# GB/T 22239-2019 信息安全技术 网络安全等级保护基本要求"
        result = filename_to_title("GB_T_22239.pdf", content)
        assert result == "GB/T 22239-2019 信息安全技术 网络安全等级保护基本要求"


# ═══════════════════════════════════════════════════════
# deai_postprocess
# ═══════════════════════════════════════════════════════

class TestDeaiPostprocess:
    def test_removes_zongshang(self):
        text = "综上所述，这个方案是可行的。"
        result = deai_postprocess(text)
        assert "综上所述" not in result

    def test_removes_zhidezhuyi(self):
        text = "值得注意的是，系统已经上线。"
        result = deai_postprocess(text)
        assert "值得注意的是" not in result

    def test_replaces_juyou(self):
        text = "这个功能具有重要意义"
        result = deai_postprocess(text)
        assert "有具体影响" in result
        assert "具有重要意义" not in result

    def test_replaces_budan_ermu(self):
        text = "不仅提升了效率，而且降低了成本"
        result = deai_postprocess(text)
        assert "不仅" not in result
        assert "同时" in result

    def test_removes_furthermore(self):
        text = "此外，系统还支持批量处理。"
        result = deai_postprocess(text)
        assert "此外，" not in result

    def test_fixes_punctuation_spacing(self):
        text = "测试 。 内容 ！"
        result = deai_postprocess(text)
        # Should fix space after punctuation
        assert "。" in result
        assert result.count("。") == 1 or "。" in result

    def test_collapses_blank_lines(self):
        text = "A\n\n\n\nB"
        result = deai_postprocess(text)
        assert "\n\n\n" not in result

    # ── 2026-09-17 回归：标点规则不得吃掉换行（表格表头必须独占一行）──
    def test_punctuation_rule_keeps_newlines(self):
        r"""`\s+` → `[ \t]+`：标点后的换行必须保留（原写法会把表格表头粘到上行）。"""
        text = "省级 15.00 万元。\n\n| 地市 | 金额 |\n|---|---|\n| 东莞 | 9.60 |"
        result = deai_postprocess(text)
        assert "万元。\n\n| 地市" in result
        assert "万元。|" not in result
        assert result.count("\n") >= 4  # 4 行表格结构未被压平

    def test_punctuation_rule_strips_fullwidth_space(self):
        """CC 建议 1：`[ \\t]+` 会漏掉 U+3000 全角空格；`[^\\S\\r\\n]+` 应剥离它。"""
        assert deai_postprocess("结论。\u3000下一句") == "结论。下一句"
        out = deai_postprocess("金额如下：\u3000\u3000见表。")
        assert "\u3000" not in out, repr(out)

    def test_punctuation_rule_still_fixes_inline_space(self):
        text = "测试 。 内容 ！ 结束"
        result = deai_postprocess(text)
        assert "。内容" in result
        assert "！结束" in result

    # ── R3-5: 内部错误文案过滤 ──
    def test_keeps_normal_answer_unchanged(self):
        text = "根据《GB/T 21671-2008》，系统应满足下列要求。\n验收测试需覆盖全部功能点。"
        result = deai_postprocess(text)
        assert "21671-2008" in result
        assert "验收测试" in result

    def test_strips_traceback_block(self):
        text = "结论如下：\nTraceback (most recent call last):\n  File \"gen.py\", line 42\n    raise ValueError\nLLM API 重试 3 次后仍失败: Read timed out\n\n正确答案是 A。"
        result = deai_postprocess(text)
        assert "Traceback" not in result
        assert "Read timed out" not in result
        assert "正确答案是 A" in result

    def test_strips_internal_error_lines(self):
        text = "rate limit exceeded: retry later\n实际回答内容不变。"
        result = deai_postprocess(text)
        assert "rate limit" not in result
        assert "实际回答内容" in result

    def test_error_only_answer_kept_for_degraded_handling(self):
        # 整段都是错误文案 → 保留原文（上层 degraded/拒答逻辑兜底，避免空 answer 冒充成功）
        text = "LLM API 返回异常: server error"
        result = deai_postprocess(text)
        assert result  # 非空
        assert "server error" in result


# ═══════════════════════════════════════════════════════
# _extract_numbers
# ═══════════════════════════════════════════════════════

class TestExtractNumbers:
    def test_extracts_arabic_numbers(self):
        nums = _extract_numbers("预算500万元，工期180天")
        # The regex captures numbers with optional unit suffixes
        assert any("500" in n for n in nums)
        assert "180" in nums

    def test_extracts_decimal_numbers(self):
        nums = _extract_numbers("评分3.5分")
        assert "3.5" in nums

    def test_extracts_numbers_with_units(self):
        nums = _extract_numbers("投资500万")
        # The regex captures numbers optionally followed by 万/亿
        assert any("500" in n for n in nums)


# ═══════════════════════════════════════════════════════
# _fix_encoding
# ═══════════════════════════════════════════════════════

class TestFixEncoding:
    def test_normal_text_unchanged(self):
        text = "正常中文文本"
        assert _fix_encoding(text) == text

    def test_latin1_passthrough(self):
        text = "hello"
        assert _fix_encoding(text) == text
