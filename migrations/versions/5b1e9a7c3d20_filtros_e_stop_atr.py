"""filtros de entrada nos robôs e stop/alvo pelo ATR nas posições

Revision ID: 5b1e9a7c3d20
Revises: c07fa3b20811
Create Date: 2026-10-22 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "5b1e9a7c3d20"
down_revision = "c07fa3b20811"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("filters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("positions", sa.Column("stop_price", sa.Numeric(28, 10), nullable=True))
    op.add_column("positions", sa.Column("take_price", sa.Numeric(28, 10), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "take_price")
    op.drop_column("positions", "stop_price")
    op.drop_column("bots", "filters")
