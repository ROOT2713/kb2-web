"""Database setup — SQLAlchemy engine, session, base model."""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

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

    # ── Wiki tables ──
    with engine.connect() as conn:
        conn.execute(sa_text(
            "CREATE TABLE IF NOT EXISTS wiki_entries ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  title TEXT NOT NULL,"
            "  standard_no TEXT DEFAULT '',"
            "  category TEXT DEFAULT '',"
            "  subcategory TEXT DEFAULT '',"
            "  tags TEXT DEFAULT '[]',"
            "  summary TEXT DEFAULT '',"
            "  content TEXT DEFAULT '{}',"
            "  source_doc_id TEXT DEFAULT '',"
            "  importance INTEGER DEFAULT 0,"
            "  status TEXT DEFAULT 'draft',"
            "  created_at TEXT NOT NULL,"
            "  updated_at TEXT NOT NULL,"
            "  bank_hint TEXT DEFAULT ''"
            ")"
        ))
        conn.execute(sa_text(
            "CREATE TABLE IF NOT EXISTS wiki_relations ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  source_entry_id INTEGER NOT NULL,"
            "  target_entry_id INTEGER NOT NULL,"
            "  relation_type TEXT NOT NULL,"
            "  description TEXT DEFAULT ''"
            ")"
        ))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_wiki_entries_std ON wiki_entries(standard_no)"
        ))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_wiki_entries_cat ON wiki_entries(category)"
        ))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_wiki_relations_src ON wiki_relations(source_entry_id)"
        ))
        # ── 迁移：wiki_entries.bank_hint（2026-10-12 补齐）──
        # 缺陷：建表 DDL 长期缺 bank_hint，而 wiki_service.retrieve_for_query()
        # 明确 SELECT bank_hint ⇒ 任何「按此 schema 新建」的库都会让 wiki 检索
        # 抛 OperationalError (no such column) 并被 except 吞掉 → wiki 检索静默失效。
        # 生产库侥幸有该列（历史上手工 ALTER），故缺陷一直潜伏。
        _cols = {r[1] for r in conn.execute(
            sa_text("PRAGMA table_info(wiki_entries)")
        ).fetchall()}
        if _cols and "bank_hint" not in _cols:
            conn.execute(sa_text(
                "ALTER TABLE wiki_entries ADD COLUMN bank_hint TEXT DEFAULT ''"
            ))
            logger.warning("[MIGRATE] wiki_entries 补建 bank_hint 列完成")
        conn.commit()
