"""Add published_date + geo_scope fields for time/hierarchy tiebreaker

Revision ID: b3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa


revision = "b3d4e5f6a7b8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents",
        sa.Column("published_date", sa.Date, nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("geo_scope", sa.String(32), nullable=True),
    )


def downgrade():
    op.drop_column("documents", "published_date")
    op.drop_column("documents", "geo_scope")
