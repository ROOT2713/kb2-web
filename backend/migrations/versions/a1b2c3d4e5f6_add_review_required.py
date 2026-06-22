"""Phase A: Add review_required + last_confirmed fields to documents

Revision ID: a1b2c3d4e5f6
Revises: c5f6352f0ecf
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "c5f6352f0ecf"
branch_labels = None
depends_on = None


def upgrade():
    # ── Add review_required column ──
    op.add_column(
        "documents",
        sa.Column("review_required", sa.Integer, server_default="0"),
    )

    # ── Add last_confirmed column ──
    op.add_column(
        "documents",
        sa.Column("last_confirmed", sa.DateTime, nullable=True),
    )

    # ── Backfill last_confirmed = verified_at (or created_at) ──
    op.execute("""
        UPDATE documents
        SET last_confirmed = COALESCE(verified_at, created_at)
        WHERE last_confirmed IS NULL AND status = 'active'
    """)

    # ── Backfill review_required = 1 for documents with any concept confidence < 0.7 ──
    op.execute("""
        UPDATE documents
        SET review_required = 1
        WHERE status = 'active'
          AND review_required = 0
          AND doc_id IN (
              SELECT DISTINCT c.doc_id
              FROM concepts c
              WHERE c.status = 'active'
                AND c.confidence IS NOT NULL
                AND c.confidence < 0.7
          )
    """)


def downgrade():
    op.drop_column("documents", "last_confirmed")
    op.drop_column("documents", "review_required")
