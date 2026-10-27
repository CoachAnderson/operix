"""qualidade de execução das ordens (preço e momento do sinal, momento da execução, taxas da operação)

Revision ID: 6c2d8e4f9a17
Revises: 3e7a9c1d5f42
Create Date: 2026-10-24 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "6c2d8e4f9a17"
down_revision = "3e7a9c1d5f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("ref_price", sa.Numeric(28, 10), nullable=True))
    op.add_column("orders", sa.Column("signal_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("trade_fees", sa.Numeric(28, 10), nullable=True))


def downgrade() -> None:
    for c in ("trade_fees", "filled_at", "signal_at", "ref_price"):
        op.drop_column("orders", c)
