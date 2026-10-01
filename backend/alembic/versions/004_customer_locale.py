"""customer language and time zone

Revision ID: 004
Revises: 003
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchases", sa.Column("locale", sa.String(5), nullable=False, server_default="fr"))
    op.add_column("purchases", sa.Column("customer_timezone", sa.String(64)))


def downgrade() -> None:
    op.drop_column("purchases", "customer_timezone")
    op.drop_column("purchases", "locale")
