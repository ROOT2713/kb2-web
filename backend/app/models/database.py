"""Database setup — SQLAlchemy engine, session, base model."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(settings.db_url, echo=settings.debug, connect_args={"timeout": 30})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency: yields a DB session, auto-closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables (idempotent via CREATE TABLE IF NOT EXISTS).

    Model classes must be imported prior so they register with Base.metadata.
    """
    # Ensure all model classes are registered with Base
    import app.models.document     # noqa: F401 — Document + ParentChunk
    import app.models.cache        # noqa: F401
    import app.models.synonym      # noqa: F401
    import app.models.user         # noqa: F401 — User (admin/viewer)
    import app.models.upload_task  # noqa: F401 — UploadTask
    import app.models.audit        # noqa: F401 — AuditLog

    Base.metadata.create_all(bind=engine)

    # ── Query log table (raw SQL, not ORM) ──
    from sqlalchemy import text as sa_text
    with engine.connect() as conn:
        conn.execute(sa_text(
            "CREATE TABLE IF NOT EXISTS query_log ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  query_text TEXT,"
            "  bank TEXT DEFAULT '',"
            "  timestamp TEXT,"
            "  answer_length INTEGER DEFAULT 0,"
            "  source_count INTEGER DEFAULT 0,"
            "  rejected INTEGER DEFAULT 0,"
            "  rejection_reason TEXT DEFAULT '',"
            "  latency_ms INTEGER DEFAULT 0,"
            "  cache_hit INTEGER DEFAULT 0,"
            "  concept_used INTEGER DEFAULT 0"
            ")"
        ))
        conn.commit()
