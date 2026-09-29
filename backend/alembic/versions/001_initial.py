"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("stripe_checkout_session_id", sa.String(255), nullable=False, unique=True),
        sa.Column("stripe_payment_id", sa.String(255), index=True),
        sa.Column("product_id", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("hours_purchased", sa.Integer, nullable=False),
        sa.Column("hours_booked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payment_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("hours_booked >= 0 AND hours_booked <= hours_purchased", name="hours_booked_range"),
    )
    op.create_table(
        "booking_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("purchase_id", sa.Integer, sa.ForeignKey("purchases.id"), nullable=False, index=True),
        sa.Column("token", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("purchase_id", sa.Integer, sa.ForeignKey("purchases.id"), nullable=False),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("google_event_id", sa.String(255)),
        sa.Column("meet_url", sa.String(512)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("start_datetime < end_datetime", name="booking_interval_order"),
    )
    # R03 — one confirmed (initial) session per purchase.
    op.create_index(
        "uq_bookings_one_confirmed_per_purchase",
        "bookings",
        ["purchase_id"],
        unique=True,
        postgresql_where=sa.text("status = 'confirmed'"),
    )
    # R10 — confirmed bookings can never overlap.
    op.execute(
        "ALTER TABLE bookings ADD CONSTRAINT ex_bookings_no_overlap "
        "EXCLUDE USING gist (tstzrange(start_datetime, end_datetime) WITH &&) "
        "WHERE (status = 'confirmed')"
    )
    op.create_table(
        "calendar_sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("google_calendar_id", sa.String(512), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_duration_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("slot_step_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("minimum_notice_min", sa.Integer, nullable=False, server_default="1440"),
        sa.Column("maximum_window_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("buffer_before_min", sa.Integer, nullable=False, server_default="15"),
        sa.Column("buffer_after_min", sa.Integer, nullable=False, server_default="15"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Paris"),
        sa.Column("booking_calendar_id", sa.String(512), nullable=False, server_default="primary"),
        sa.Column("meet_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("admin_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("consultant_name", sa.String(255), nullable=False, server_default="Suan Tay"),
    )
    op.create_table(
        "availability_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("weekday", sa.SmallInteger, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        sa.CheckConstraint("start_time < end_time", name="rule_interval_order"),
    )
    op.create_table(
        "stripe_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.Text),
    )


def downgrade() -> None:
    for table in (
        "stripe_events",
        "availability_rules",
        "settings",
        "calendar_sources",
        "bookings",
        "booking_tokens",
        "purchases",
        "customers",
    ):
        op.drop_table(table)
