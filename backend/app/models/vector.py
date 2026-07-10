"""pgvector ORM model — VectorChunk for PgVectorStore."""
import datetime
from sqlalchemy import Column, String, Text, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
from app.models.database import Base


class VectorChunk(Base):
    __tablename__ = "vector_chunks"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    doc_id = Column(String(64), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    bank = Column(String(64), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024))  # pgvector type
    metadata_ = Column("metadata", JSONB, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
