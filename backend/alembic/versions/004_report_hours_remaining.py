"""session reports keep the hours left when the session ended

The client may book the next session before the summary is drafted: the live hours_remaining of the purchase
would then call it the last session.

Revision ID: 004
Revises: 003
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_reports", sa.Column("hours_remaining", sa.Integer))
    # Reports created before this column: the hours left now are the best estimate.
    op.execute(
        "UPDATE session_reports r SET hours_remaining = p.hours_purchased - p.hours_booked "
        "FROM bookings b JOIN purchases p ON p.id = b.purchase_id WHERE b.id = r.booking_id"
    )
    op.alter_column("session_reports", "hours_remaining", nullable=False)


def downgrade() -> None:
    op.drop_column("session_reports", "hours_remaining")
