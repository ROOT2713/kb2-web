"""OKF Concept model — 语义概念单元（clause-level, 独立于 chunk）。

LLM Wiki V2 核心概念：知识最小粒度是 concept（语义自包含），不是 chunk（技术分块）。
每个 concept 有独立的 concept_id namespace、summary、confidence、向量。
"""

from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Integer, Float, Index
from app.models.database import Base


class Concept(Base):
    """单个知识概念 — 从文档的 clause/section 提取的语义自包含单元。"""
    __tablename__ = "concepts"

    concept_id = Column(String, primary_key=True)      # e.g. "standards/security/gb-50116/clause-4.1"
    doc_id = Column(String, nullable=False, index=True) # 来源文档
    parent_idx = Column(Integer, nullable=False)         # 对应 parent_chunks 的 parent_idx
    title = Column(String, default="")                   # 条款/章节标题
    summary = Column(Text, default="")                   # LLM 生成的 1-3 句摘要
    content = Column(Text, nullable=False, default="")   # 原文内容
    confidence = Column(Float, default=0.5)              # 概念级置信度
    status = Column(String, default="active", index=True)  # active|draft|deprecated
    access_count = Column(Integer, default=0)            # 被检索命中次数
    last_accessed_at = Column(DateTime, nullable=True)   # 最后被访问时间
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_concepts_doc_parent", "doc_id", "parent_idx"),
        Index("ix_concepts_status_confidence", "status", "confidence"),
    )

    def to_dict(self) -> dict:
        content_val = self.content if isinstance(self.content, str) else ""
        return {
            "concept_id": self.concept_id,
            "doc_id": self.doc_id,
            "parent_idx": self.parent_idx,
            "title": self.title,
            "summary": self.summary,
            "content": content_val[:500] + "..." if len(content_val) > 500 else content_val,
            "confidence": self.confidence,
            "status": self.status,
            "access_count": self.access_count,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else None,
        }

    def to_full_dict(self) -> dict:
        """完整内容（不含截断），供 API 返回。"""
        d = self.to_dict()
        d["content"] = self.content
        return d


class KGTriple(Base):
    """知识图谱三元组 — subject → predicate → object 关系。"""
    __tablename__ = "kg_triples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_type = Column(String, nullable=False)    # document|concept|standard|clause
    subject_id = Column(String, nullable=False, index=True)
    predicate = Column(String, nullable=False)        # references|supersedes|defines|applies_to|cites|derives_from
    object_type = Column(String, nullable=False)
    object_id = Column(String, nullable=False, index=True)
    doc_id = Column(String, nullable=True, index=True)  # 来源文档
    confidence = Column(Float, default=1.0)
    evidence = Column(Text, nullable=True)            # 引用证据原文片段
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_kg_subj_pred", "subject_id", "predicate"),
        Index("ix_kg_obj_pred", "object_id", "predicate"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "doc_id": self.doc_id,
            "confidence": self.confidence,
        }


class QualityGateLog(Base):
    """质量门禁日志 — 记录每次文档质量检查结果。"""
    __tablename__ = "quality_gate_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String, nullable=False, index=True)
    gate_level = Column(String, nullable=False)      # G1|G2|G3
    passed = Column(Integer, nullable=False, default=0)  # 0=fail, 1=pass
    score = Column(Float, nullable=True)
    issues = Column(Text, nullable=True)              # JSON array of issues
    checked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "gate_level": self.gate_level,
            "passed": bool(self.passed),
            "score": self.score,
            "issues": self.issues,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }
