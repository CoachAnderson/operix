"""aparência do painel por usuário (tema, cores, fonte)

Revision ID: 3e7a9c1d5f42
Revises: 8d4c2f6a1b93
Create Date: 2026-10-22 20:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "3e7a9c1d5f42"
down_revision = "8d4c2f6a1b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("appearance", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "appearance")
