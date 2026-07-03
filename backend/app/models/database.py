"""Database setup — SQLAlchemy engine, session, base model."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(settings.db_url, echo=settings.debug)
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

    Base.metadata.create_all(bind=engine)
