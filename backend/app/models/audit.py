"""审计日志 ORM 模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime

from app.models.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True, default="unknown")
    query = Column(String(500), nullable=False)
    answer = Column(Text, nullable=True)
    sources = Column(Text, nullable=True)  # JSON string
    tokens_used = Column(Integer, default=0)
    cache_hit = Column(Integer, default=0)  # 0=no, 1=exact, 2=semantic
    response_ms = Column(Integer, default=0)
    rejected = Column(String(32), nullable=True)  # confidence_reject type or NULL
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
