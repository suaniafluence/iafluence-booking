"""per-customer choice: next-session link sent automatically or left as a draft

Revision ID: 002
Revises: 001
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("auto_send_next_link", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("customers", "auto_send_next_link")
