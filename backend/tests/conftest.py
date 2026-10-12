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
os.environ.setdefault("ADMIN_USERNAME", "test_admin")  # role-check bypass in tests
os.environ.setdefault("ADMIN_PASSWORD", "")            # disable auth in dev
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("HINDSIGHT_URL", "http://fake-hindsight:9999")

def pytest_addoption(parser):
    """Allow --run-integration flag for golden-query regression tests that hit production DB."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require production DB and external services",
    )


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
    # Raw-SQL table: concept_contradictions (crystallization checks, 2026-08-14)
    from app.services.crystallization_light import CREATE_TABLE_SQL, INDEX_SQL
    with _engine.begin() as conn:
        conn.execute(sa_text(CREATE_TABLE_SQL))
        for stmt in INDEX_SQL.split(";"):  # SQLite 一次只能执行一条语句
            stmt = stmt.strip()
            if stmt:
                conn.execute(sa_text(stmt))
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
    from app.config import settings as _settings

    async def _no_jwt():
        # admin config user always passes require_role checks
        return _settings.admin_username

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
def mock_get_active_banks(monkeypatch):
    """Return empty active banks list."""
    import app.services.retrieval as retrieval

    async def _fake():
        return []

    monkeypatch.setattr(retrieval, "_get_active_banks", _fake)
    return _fake


@pytest.fixture(autouse=True)
def _reset_vector_store_singleton():
    """每个测试结束后丢弃 PgVectorStore 单例 —— 其 asyncpg 池绑定在「已关闭的事件循环」上。

    根因（2026-10-12 二分定位实测）：
      `app.repositories.vector_repo.get_vector_store()` 返回**模块级单例**
      `_store_instance`，其 `_pool` 由**首次调用它的那个 asyncio 事件循环**创建
      （`PgVectorStore._get_pool()`）。pytest 每个测试跑在独立 loop 上，前一个 loop
      关闭后单例仍持有**死池** ⇒ 后续任何 `pg recall` 抛 `Event loop is closed`，
      而 `retrieval.recall()` 用 broad `except Exception` 吞掉并 `return []`
      ⇒ **静默 merged=0 / 召回为空**，表现为「测试莫名少数据」。

    触发条件：把 `recall` 从「mock 返回 []」改为**真实执行**之后才暴露
    （此前该文件从不真正触达 pg，单例池从不建立）。生产不受影响 —— uvicorn
    只有一个长驻 loop，单例语义正确；这是**测试隔离**缺陷。

    对照组（A/B 单变量，`-p no:randomly`）：
      无本夹具：`tests/integration/test_checklist_query.py` + 目标用例 → 1 failed
      有本夹具：同一组合 → 1 passed
    """
    yield
    import app.repositories.vector_repo as _vr

    inst = getattr(_vr, "_store_instance", None)
    _vr._store_instance = None
    if inst is not None and getattr(inst, "_pool", None) is not None:
        # 池所属 loop 已关闭，无法 await close()；直接丢弃引用（连接早已失效）
        inst._pool = None

