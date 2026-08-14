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
    """Pre-flight duplicate content rejection 集成测试（异步上传契约 2026-08-14）。

    上传接口已异步化：POST /api/upload 返回 {task_id, status: "pending"}，
    重复/G1 检查在后台任务中执行，终态经 GET /api/upload/tasks/{task_id} 查询。
    """

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

    def _wait_task(self, client, task_id, timeout=15):
        """Poll upload task until terminal status (done/failed)."""
        import time
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            resp = client.get(f"/api/upload/tasks/{task_id}")
            assert resp.status_code == 200, f"task query failed: {resp.status_code}"
            last = resp.json()
            if last["status"] in ("done", "failed"):
                return last
            time.sleep(0.2)
        raise AssertionError(f"task {task_id} 超时未完成: {last}")

    def test_duplicate_content_rejected(self, client, db_session):
        """重复内容第二次上传：后台任务终态 failed + duplicate_check。"""
        text = "这是用于测试重复检测的文档内容。" * 20
        title = "重复检测测试文档"

        # First upload accepted asynchronously → done
        resp1 = self._upload_text(client, text, title)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "pending"
        assert "task_id" in data1
        task1 = self._wait_task(client, data1["task_id"])
        assert task1["status"] == "done", f"首份文档应入库成功: {task1}"

        # Second upload of same content → async duplicate rejection
        resp2 = self._upload_text(client, text, title)
        assert resp2.status_code == 200
        task2 = self._wait_task(client, resp2.json()["task_id"])
        assert task2["status"] == "failed", f"重复内容应被拒绝: {task2}"
        assert task2.get("stage") == "duplicate_check", (
            f"应为 duplicate_check 阶段失败: {task2}"
        )
        assert "dup" in (task2.get("error_message") or "").lower()

    def test_different_content_passes(self, client, db_session):
        """不同内容正常通过（两个任务终态均 done）。"""
        text1 = "第一份完全不同的文档内容。" * 20
        text2 = "第二份完全不同的文档内容。" * 20

        resp1 = self._upload_text(client, text1, "文档A")
        assert resp1.status_code == 200
        task1 = self._wait_task(client, resp1.json()["task_id"])
        assert task1["status"] == "done", f"文档A 应成功: {task1}"

        resp2 = self._upload_text(client, text2, "文档B")
        assert resp2.status_code == 200
        task2 = self._wait_task(client, resp2.json()["task_id"])
        assert task2["status"] == "done", f"文档B 应成功: {task2}"

    def test_g1_fail_rejected(self, client, db_session):
        """G1 硬检查不通过：后台任务终态 failed + quality_gate。"""
        text = "短"  # Too short
        title = ""

        resp = self._upload_text(client, text, title)
        assert resp.status_code == 200
        task = self._wait_task(client, resp.json()["task_id"])
        assert task["status"] == "failed", f"G1 不过应失败: {task}"
        assert task.get("stage") == "quality_gate", (
            f"应为 quality_gate 阶段失败: {task}"
        )
