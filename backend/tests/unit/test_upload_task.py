"""Tests for UploadTask model and async upload state machine."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.database import Base
from app.models.upload_task import UploadTask


@pytest.fixture
def db_session():
    """In-memory SQLite session for isolated tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()


class TestUploadTaskModel:
    def test_create_task(self, db_session):
        task_id = str(uuid.uuid4())
        task = UploadTask(id=task_id, status="pending", filename="test.pdf", progress=0.0, stage="queued")
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        assert saved is not None
        assert saved.status == "pending"
        assert saved.filename == "test.pdf"
        assert saved.progress == 0.0
        assert saved.stage == "queued"

    def test_update_task_progress(self, db_session):
        task_id = str(uuid.uuid4())
        task = UploadTask(id=task_id, status="pending", filename="doc.docx")
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        saved.status = "processing"
        saved.progress = 0.5
        saved.stage = "parsing"
        db_session.commit()

        updated = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        assert updated.status == "processing"
        assert updated.progress == 0.5
        assert updated.stage == "parsing"

    def test_task_failure(self, db_session):
        task_id = str(uuid.uuid4())
        task = UploadTask(id=task_id, status="processing", filename="bad.pdf", progress=0.1, stage="parsing")
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        saved.status = "failed"
        saved.error_message = "parse error"
        db_session.commit()

        failed = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        assert failed.status == "failed"
        assert "parse" in failed.error_message

    def test_task_with_result(self, db_session):
        import json
        task_id = str(uuid.uuid4())
        result_json = json.dumps({"ok": True, "doc_id": "abc123", "title": "test"})
        task = UploadTask(
            id=task_id, status="done", filename="done.pdf",
            progress=1.0, stage="complete",
            result_doc_id="abc123", result=result_json,
        )
        db_session.add(task)
        db_session.commit()

        saved = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        assert saved.status == "done"
        assert saved.result_doc_id == "abc123"
        parsed = json.loads(saved.result)
        assert parsed["ok"] is True
        assert parsed["doc_id"] == "abc123"

    def test_task_query_by_id(self, db_session):
        task_id = str(uuid.uuid4())
        db_session.add(UploadTask(id=task_id, status="pending", filename="a.txt"))
        db_session.commit()

        found = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        assert found is not None
        assert found.filename == "a.txt"

        not_found = db_session.query(UploadTask).filter(UploadTask.id == "nonexistent").first()
        assert not_found is None

    def test_default_created_at(self, db_session):
        task_id = str(uuid.uuid4())
        db_session.add(UploadTask(id=task_id, status="pending", filename="ts.pdf"))
        db_session.commit()

        task = db_session.query(UploadTask).filter(UploadTask.id == task_id).first()
        assert task.created_at is not None
        assert task.updated_at is not None
