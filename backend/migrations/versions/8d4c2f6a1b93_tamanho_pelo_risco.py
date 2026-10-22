"""tamanho da posição pelo risco e limite de alavancagem

Revision ID: 8d4c2f6a1b93
Revises: 5b1e9a7c3d20
Create Date: 2026-10-22 10:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = "8d4c2f6a1b93"
down_revision = "5b1e9a7c3d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("sizing_mode", sa.String(10), nullable=False, server_default="fixed"))
    op.add_column("bots", sa.Column("risk_pct", sa.Numeric(6, 3), nullable=True))
    op.add_column("bots", sa.Column("max_leverage", sa.Numeric(8, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "max_leverage")
    op.drop_column("bots", "risk_pct")
    op.drop_column("bots", "sizing_mode")
