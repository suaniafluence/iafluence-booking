"""Fireflies connection from the admin

Revision ID: 005
Revises: 004
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("fireflies_api_key_enc", sa.Text()))
    op.add_column("settings", sa.Column("fireflies_email", sa.String(320)))
    op.add_column("settings", sa.Column("fireflies_name", sa.String(255)))
    op.add_column("settings", sa.Column("fireflies_connected_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("settings", "fireflies_connected_at")
    op.drop_column("settings", "fireflies_name")
    op.drop_column("settings", "fireflies_email")
    op.drop_column("settings", "fireflies_api_key_enc")
