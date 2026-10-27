"""prazo do acesso liberado pelo admin

Revision ID: 9a4b6d2e8c31
Revises: 6c2d8e4f9a17
Create Date: 2026-10-27 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "9a4b6d2e8c31"
down_revision = "6c2d8e4f9a17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "expires_at")
