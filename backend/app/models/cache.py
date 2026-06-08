"""Query cache model.

Replaces: kb-web server.py query_cache SQLite table

v1 schema: cache_id, query_text, query_embedding(BLOB), bank, answer,
           sources_json, hit_count, created_at, last_hit_at, ttl_seconds, doc_ids_json
"""

from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Integer, LargeBinary, Text
from app.models.database import Base


class QueryCache(Base):
    __tablename__ = "query_cache"

    cache_id = Column(String, primary_key=True)
    query_text = Column(Text, nullable=False)
    query_embedding = Column(LargeBinary, nullable=True)
    bank = Column(String, default="all", index=True)
    answer = Column(Text, nullable=False, default="")
    sources_json = Column(Text, default="[]")
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_hit_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ttl_seconds = Column(Integer, default=86400)
    doc_ids_json = Column(Text, default="[]")
