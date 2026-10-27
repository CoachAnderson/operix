"""estado dos robôs de grade e compra programada (Grid e DCA)

Revision ID: c3f8a1d6e2b4
Revises: 9a4b6d2e8c31
Create Date: 2026-10-27 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "c3f8a1d6e2b4"
down_revision = "9a4b6d2e8c31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "state")
