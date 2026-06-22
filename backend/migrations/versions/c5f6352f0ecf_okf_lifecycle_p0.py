"""P0: OKF lifecycle — Document 扩展 + Concept/KGTriple/QualityGateLog 三表

Revision ID: c5f6352f0ecf
Revises: 
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "c5f6352f0ecf"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ── Document 表：新增 OKF lifecycle 列 ──
    op.add_column("documents", sa.Column("concept_id", sa.String, nullable=True))
    op.add_column("documents", sa.Column("domain", sa.String, nullable=True))
    op.add_column("documents", sa.Column("subdomain", sa.String, nullable=True))
    op.add_column("documents", sa.Column("profile_confidence", sa.Float, nullable=True))
    op.add_column("documents", sa.Column("status", sa.String, server_default="active"))
    op.add_column("documents", sa.Column("superseded_by", sa.String, nullable=True))
    op.add_column("documents", sa.Column("supersedes", sa.String, nullable=True))
    op.add_column("documents", sa.Column("stale_at", sa.DateTime, nullable=True))
    op.add_column("documents", sa.Column("stale_reason", sa.String, nullable=True))
    op.add_column("documents", sa.Column("version", sa.String, server_default="1.0.0"))
    op.add_column("documents", sa.Column("source_url", sa.String, nullable=True))
    op.add_column("documents", sa.Column("chunk_count", sa.Integer, server_default="0"))

    op.create_index("ix_documents_concept_id", "documents", ["concept_id"])
    op.create_index("ix_documents_domain", "documents", ["domain"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_superseded_by", "documents", ["superseded_by"])
    op.create_index("ix_documents_domain_status", "documents", ["domain", "status"])

    # ── Concepts 表 ──
    op.create_table(
        "concepts",
        sa.Column("concept_id", sa.String, primary_key=True),
        sa.Column("doc_id", sa.String, nullable=False),
        sa.Column("parent_idx", sa.Integer, nullable=False),
        sa.Column("title", sa.String, server_default=""),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("confidence", sa.Float, server_default="0.5"),
        sa.Column("status", sa.String, server_default="active"),
        sa.Column("access_count", sa.Integer, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_concepts_doc_id", "concepts", ["doc_id"])
    op.create_index("ix_concepts_status", "concepts", ["status"])
    op.create_index("ix_concepts_doc_parent", "concepts", ["doc_id", "parent_idx"])
    op.create_index("ix_concepts_status_confidence", "concepts", ["status", "confidence"])

    # ── KG Triples 表 ──
    op.create_table(
        "kg_triples",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("subject_type", sa.String, nullable=False),
        sa.Column("subject_id", sa.String, nullable=False),
        sa.Column("predicate", sa.String, nullable=False),
        sa.Column("object_type", sa.String, nullable=False),
        sa.Column("object_id", sa.String, nullable=False),
        sa.Column("doc_id", sa.String, nullable=True),
        sa.Column("confidence", sa.Float, server_default="1.0"),
        sa.Column("evidence", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_kg_triples_subject_id", "kg_triples", ["subject_id"])
    op.create_index("ix_kg_triples_object_id", "kg_triples", ["object_id"])
    op.create_index("ix_kg_triples_doc_id", "kg_triples", ["doc_id"])
    op.create_index("ix_kg_subj_pred", "kg_triples", ["subject_id", "predicate"])
    op.create_index("ix_kg_obj_pred", "kg_triples", ["object_id", "predicate"])

    # ── Quality Gate Log 表 ──
    op.create_table(
        "quality_gate_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("doc_id", sa.String, nullable=False),
        sa.Column("gate_level", sa.String, nullable=False),
        sa.Column("passed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("issues", sa.Text, nullable=True),
        sa.Column("checked_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_quality_gate_log_doc_id", "quality_gate_log", ["doc_id"])


def downgrade():
    op.drop_table("quality_gate_log")
    op.drop_table("kg_triples")
    op.drop_table("concepts")

    for idx in [
        "ix_documents_domain_status",
        "ix_documents_superseded_by",
        "ix_documents_status",
        "ix_documents_domain",
        "ix_documents_concept_id",
    ]:
        op.drop_index(idx, table_name="documents")

    for col in [
        "chunk_count", "source_url", "version",
        "stale_reason", "stale_at", "supersedes", "superseded_by",
        "status", "profile_confidence", "subdomain", "domain", "concept_id",
    ]:
        op.drop_column("documents", col)
