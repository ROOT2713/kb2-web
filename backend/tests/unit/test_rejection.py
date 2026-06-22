"""Tests for Phase B #6 — Pre-flight fingerprint rejection + quality gate hard rejection."""

import pytest
import hashlib
import json
from datetime import datetime, timezone

from app.services.quality_gates import hard_check_g1
from app.models.document import Document
from app.models.concept import Concept


class TestHardCheckG1:
    """硬模式 G1 检查单元测试。"""

    def test_pass_normal_content(self):
        """正常内容通过 G1 硬检查。"""
        text = "这是一段正常的文档内容。" * 20  # ~280 chars
        title = "测试文档标题"
        result = hard_check_g1(text, title)
        assert result["passed"] is True
        assert len(result["issues"]) == 0

    def test_fail_short_content(self):
        """内容过短（<100 字符）fail。"""
        text = "短文本"
        title = "测试"
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        assert any("过短" in i for i in result["issues"])

    def test_fail_garbled_content(self):
        """乱码占比过高 fail。"""
        # 构造 40% 乱码内容
        garbage = "�" * 40
        normal = "正常内容。" * 10
        text = garbage + normal
        title = "乱码文档"
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        assert any("乱码" in i for i in result["issues"])

    def test_fail_empty_title(self):
        """标题为空 fail。"""
        text = "这是正常的文档内容。" * 20
        title = ""
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        assert any("标题" in i for i in result["issues"])

    def test_fail_whitespace_title(self):
        """标题全空白 fail。"""
        text = "这是正常的文档内容。" * 20
        title = "   \t  \n  "
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        assert any("标题" in i for i in result["issues"])

    def test_fail_repeated_chars(self):
        """纯重复字符 fail。"""
        text = "........." * 30
        title = "测试"
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        assert any("重复" in i or "单一" in i for i in result["issues"])

    def test_fail_single_char_dominant(self):
        """同一字符占比 >80% fail。"""
        text = "A" * 100 + "正常内容" * 2
        title = "测试"
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        assert any("单一字符" in i or "重复" in i for i in result["issues"])

    def test_pass_empty_text_but_short(self):
        """空文本同时触发多条规则。"""
        text = ""
        title = ""
        result = hard_check_g1(text, title)
        assert result["passed"] is False
        # 应该同时有 "过短" 和 "标题" 问题
        assert len(result["issues"]) >= 2


class TestDuplicateContentRejection:
    """Pre-flight duplicate content rejection 集成测试。"""

    def _upload_text(self, client, text, title="测试文档"):
        """Helper: upload text content via the /api/upload endpoint."""
        # We need to send as multipart form with a file
        # Create a virtual file from text
        import io
        return client.post(
            "/api/upload",
            files={"file": ("test.txt", io.BytesIO(text.encode("utf-8")), "text/plain")},
            data={"title": title, "bank": "general", "confirm_quality": "true"},
        )

    def test_duplicate_content_returns_422(self, client, db_session):
        """第二次上传相同内容返回 422 DUPLICATE_CONTENT。"""
        text = "这是用于测试重复检测的文档内容。" * 20
        title = "重复检测测试文档"

        # First upload should succeed
        resp1 = self._upload_text(client, text, title)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1.get("ok") is True

        # Second upload of same content should fail with 422
        resp2 = self._upload_text(client, text, title)
        assert resp2.status_code == 422
        detail = resp2.json().get("detail", {})
        assert detail.get("code") == "DUPLICATE_CONTENT"

    def test_different_content_passes(self, client, db_session):
        """不同内容正常通过。"""
        text1 = "第一份完全不同的文档内容。" * 20
        text2 = "第二份完全不同的文档内容。" * 20

        resp1 = self._upload_text(client, text1, "文档A")
        assert resp1.status_code == 200

        resp2 = self._upload_text(client, text2, "文档B")
        assert resp2.status_code == 200

    def test_g1_fail_returns_422(self, client, db_session):
        """G1 硬检查不通过返回 422。"""
        text = "短"  # Too short
        title = ""

        resp = self._upload_text(client, text, title)
        assert resp.status_code == 422
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "QUALITY_GATE_G1_FAIL"
