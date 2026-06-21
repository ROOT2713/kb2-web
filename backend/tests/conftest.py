"""Shared pytest fixtures for kb2-web backend tests.

Provides:
- In-memory SQLite database (no file I/O)
- FastAPI TestClient wired to that DB
- Mocked external services (Hindsight, LLM, embeddings)
"""

import os
import sys

# ── Force test-friendly env BEFORE any app import ──
os.environ.setdefault("DATABASE_URL", "sqlite://")  # unused but safe
os.environ.setdefault("ADMIN_PASSWORD", "")          # disable auth in dev
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("HINDSIGHT_URL", "http://fake-hindsight:9999")

import pytest
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# ── Build a shared in-memory engine (StaticPool keeps it alive across threads) ──
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


# ── Patch the app's database module BEFORE the app uses it ──
from app.models import database as _db_mod

_db_mod.engine = _engine
_db_mod.SessionLocal = _TestSession

# Override FastAPI dependency
from app.models.database import get_db as _orig_get_db

def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


# ── Create tables once per session ──
@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Create all DB tables in the in-memory engine."""
    from app.models.database import Base
    # Import models so they register with Base.metadata
    import app.models.document   # noqa
    import app.models.concept    # noqa — Concept, KGTriple, QualityGateLog
    import app.models.cache      # noqa
    import app.models.synonym    # noqa
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def db_session():
    """Yield a fresh DB session; rolls back after each test for isolation."""
    conn = _engine.connect()
    trans = conn.begin()
    session = _TestSession(bind=conn)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient with overridden DB dependency and mocked external services."""
    from app.main import app
    from app.models.database import get_db

    # Override get_db
    app.dependency_overrides[get_db] = lambda: db_session

    # Override require_admin to always allow (skip auth in tests)
    from app.middleware.auth import require_admin

    async def _no_auth():
        return True

    app.dependency_overrides[require_admin] = _no_auth

    # Override JWT auth to skip token validation in tests
    from app.middleware.jwt_auth import get_current_user

    async def _no_jwt():
        return "test_user"

    app.dependency_overrides[get_current_user] = _no_jwt

    # Pre-populate the synonym cache to avoid DB queries during tests
    from app.services import cache_service
    from app.services import retrieval
    retrieval._synonym_cache["rows"] = []
    retrieval._synonym_cache["ts"] = 9999999999  # far future → no refresh

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def mock_hindsight(monkeypatch):
    """Monkeypatch _hindsight_request to return empty success responses."""
    import app.services.retrieval as retrieval

    async def _fake_hindsight_request(endpoint, method="GET", json_data=None, timeout=30):
        if "stats" in endpoint:
            return {"total_nodes": 0, "total_documents": 0, "total_links": 0}
        if "documents" in endpoint and method == "GET":
            return {"items": []}
        if "memories" in endpoint:
            return {"items_count": 0}
        return {"status": "ok"}

    monkeypatch.setattr(retrieval, "_hindsight_request", _fake_hindsight_request)
    return _fake_hindsight_request


@pytest.fixture()
def mock_get_active_banks(monkeypatch):
    """Return empty active banks list."""
    import app.services.retrieval as retrieval

    async def _fake():
        return []

    monkeypatch.setattr(retrieval, "_get_active_hindsight_banks", _fake)
    return _fake
