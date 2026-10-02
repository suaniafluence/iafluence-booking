"""Free discovery calls and reports of meetings booked elsewhere

Revision ID: 006
Revises: 005
Create Date: 2026-10-02
"""
import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("kind", sa.String(16), nullable=False, server_default="session"))
    op.add_column("bookings", sa.Column("title", sa.String(255)))
    op.add_column("bookings", sa.Column("locale", sa.String(5)))
    op.add_column("bookings", sa.Column("customer_timezone", sa.String(64)))
    op.alter_column("bookings", "purchase_id", nullable=True)
    op.create_check_constraint("booking_kind", "bookings", "kind IN ('session', 'discovery', 'meeting')")
    op.create_check_constraint(
        "booking_purchase_iff_session", "bookings", "(kind = 'session') = (purchase_id IS NOT NULL)"
    )
    op.create_index(
        "uq_bookings_one_discovery_per_customer",
        "bookings",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'discovery' AND status = 'confirmed'"),
    )
    # A Fireflies recording is summarized once, whether matched to a session or picked by the admin.
    op.create_index(
        "uq_session_reports_transcript",
        "session_reports",
        ["fireflies_transcript_id"],
        unique=True,
        postgresql_where=sa.text("fireflies_transcript_id IS NOT NULL"),
    )
    op.add_column("settings", sa.Column("discovery_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("settings", sa.Column("discovery_duration_min", sa.Integer(), nullable=False, server_default="30"))


def downgrade() -> None:
    op.drop_column("settings", "discovery_duration_min")
    op.drop_column("settings", "discovery_enabled")
    op.drop_index("uq_session_reports_transcript", table_name="session_reports")
    op.drop_index("uq_bookings_one_discovery_per_customer", table_name="bookings")
    op.execute("DELETE FROM session_reports WHERE booking_id IN (SELECT id FROM bookings WHERE kind <> 'session')")
    op.execute("DELETE FROM bookings WHERE kind <> 'session'")
    op.drop_constraint("booking_purchase_iff_session", "bookings", type_="check")
    op.drop_constraint("booking_kind", "bookings", type_="check")
    op.alter_column("bookings", "purchase_id", nullable=False)
    op.drop_column("bookings", "customer_timezone")
    op.drop_column("bookings", "locale")
    op.drop_column("bookings", "title")
    op.drop_column("bookings", "kind")
