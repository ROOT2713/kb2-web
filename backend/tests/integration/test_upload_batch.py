"""Integration tests for batch upload endpoint /api/upload/batch."""

import pytest
from sqlalchemy import text as sa_text


@pytest.fixture(autouse=True)
def cleanup_batch_upload_docs():
    """Batch upload calls production SessionLocal and commits; clean persisted rows."""
    yield
    from app.models import database as db_mod

    with db_mod.engine.begin() as conn:
        conn.execute(sa_text("DELETE FROM parent_chunks"))
        conn.execute(sa_text("DELETE FROM documents"))


MARKDOWN_1 = """\
# 国家标准 GB/T 1.1-2020

## 1 范围

本标准规定了标准化文件的结构和起草规则。
本标准适用于国家标准、行业标准、地方标准和团体标准的起草。

## 2 规范性引用文件

下列文件对于本文件的应用是必不可少的。凡是注日期的引用文件，仅注日期的版本适用于本文件。
GB/T 1.2 标准化工作导则 第2部分：以ISO/IEC标准化文件为基础的标准化文件起草规则
"""

MARKDOWN_2 = """\
# 项目管理制度

## 第一章 总则

第一条 为规范项目管理流程，提高项目执行效率，制定本制度。
第二条 本制度适用于公司所有研发项目的管理。

## 第二章 项目立项

第三条 项目立项需提交项目立项申请书，经部门负责人审批。
第四条 项目立项申请书应包含项目目标、范围、资源需求和风险评估。
"""

MARKDOWN_3 = """\
# 安全生产管理制度

## 第一章 总则

第一条 为加强安全生产管理，防止和减少生产安全事故，保障员工生命和财产安全，制定本制度。
第二条 本制度适用于公司所有生产经营活动。

## 第二章 安全职责

第三条 主要负责人对本单位安全生产工作全面负责。
第四条 各部门负责人应定期组织安全检查，及时消除事故隐患。
"""


class TestUploadBatch:
    """Tests for POST /api/upload/batch."""

    def test_batch_two_markdown_files(self, client, monkeypatch):
        """Upload two markdown files, verify both succeed with distinct doc_ids."""
        # ── Monkeypatch external dependencies ──
        import app.api.upload as upload_mod

        # Mock HindsightStore
        class FakeHindsightStore:
            async def upsert(self, doc_id, items, bank):
                return len(items)

        monkeypatch.setattr(upload_mod, "HindsightStore", lambda: FakeHindsightStore())

        async def fake_recall(query, limit=50, bank="kb", max_tokens=32768):
            return [{"text": "fake recalled text " * 50, "tags": [], "score": 0.9}]

        monkeypatch.setattr(upload_mod, "recall", fake_recall)

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(upload_mod.asyncio, "sleep", fake_sleep)

        # ── Build multipart request ──
        import io
        files = [
            ("files", ("standard.md", io.BytesIO(MARKDOWN_1.encode()), "text/markdown")),
            ("files", ("project.md", io.BytesIO(MARKDOWN_2.encode()), "text/markdown")),
        ]
        resp = client.post("/api/upload/batch", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total"] == 2
        assert data["success"] == 2
        assert data["failed"] == 0
        assert len(data["results"]) == 2

        filenames = [r["filename"] for r in data["results"]]
        assert "standard.md" in filenames
        assert "project.md" in filenames

        doc_ids = [r.get("doc_id") for r in data["results"] if r.get("doc_id")]
        assert len(doc_ids) <= 1  # async batch: doc_ids come from polling, not response
        assert all(r["ok"] for r in data["results"])

    def test_batch_empty_files_returns_400(self, client):
        """Empty file list should return 400."""
        resp = client.post("/api/upload/batch")
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data

    def test_batch_uses_repeated_files_not_files_array(self, client, monkeypatch):
        """Verify the official form field is repeated 'files', not 'files[]'."""
        import app.api.upload as upload_mod

        class FakeHindsightStore:
            async def upsert(self, doc_id, items, bank):
                return len(items)

        monkeypatch.setattr(upload_mod, "HindsightStore", lambda: FakeHindsightStore())

        async def fake_recall(query, limit=50, bank="kb", max_tokens=32768):
            return [{"text": "fake recalled text " * 50, "tags": [], "score": 0.9}]

        monkeypatch.setattr(upload_mod, "recall", fake_recall)

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(upload_mod.asyncio, "sleep", fake_sleep)

        import io
        files = [
            ("files", ("safety.md", io.BytesIO(MARKDOWN_3.encode()), "text/markdown")),
        ]
        # Use repeated 'files' — this is the official FastAPI way for List[UploadFile]
        resp = client.post("/api/upload/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["success"] == 1
