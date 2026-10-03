"""V3 consultant cockpit: staff accounts (Google sign-in, admin / consultant roles), company profile and web research
of each customer, action plans written by Codex and refined by chat, inactivity reminders

Revision ID: 009
Revises: 008
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("google_sub", sa.String(255), unique=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_consultant", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("is_admin OR is_consultant", name="staff_has_role"),
        sa.CheckConstraint("email = lower(email)", name="staff_email_lower"),
    )
    # The address that already receives the admin emails gets both roles (one consultant today).
    op.execute(
        "INSERT INTO staff_users (email, name, is_admin, is_consultant) "
        "SELECT lower(admin_email), consultant_name, true, true FROM settings "
        "WHERE admin_email <> '' ORDER BY id LIMIT 1"
    )

    op.add_column("customers", sa.Column("consultant_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL")))
    op.add_column("customers", sa.Column("company_name", sa.String(255)))
    op.add_column("customers", sa.Column("siren", sa.String(9)))
    op.add_column("customers", sa.Column("notes", sa.Text()))
    op.add_column("customers", sa.Column("reminder_sent_at", sa.DateTime(timezone=True)))
    op.create_index("ix_customers_consultant_id", "customers", ["consultant_id"])
    op.execute("UPDATE customers SET consultant_id = (SELECT id FROM staff_users WHERE is_consultant ORDER BY id LIMIT 1)")

    op.add_column("bookings", sa.Column("message", sa.Text()))

    op.create_table(
        "customer_profiles",
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("company", JSONB()),
        sa.Column("company_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("research", JSONB()),
        sa.Column("research_status", sa.String(16)),
        sa.Column("research_error", sa.Text()),
        sa.Column("research_claimed_until", sa.DateTime(timezone=True)),
        sa.Column("research_updated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("research_status IN ('running', 'ready', 'failed')", name="profile_research_status"),
    )

    op.create_table(
        "action_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("consultant_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL")),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("purchases.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("claimed_until", sa.DateTime(timezone=True)),
        sa.Column("content", JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'generating', 'ready', 'failed')", name="action_plan_status"),
    )
    op.create_index("ix_action_plans_status", "action_plans", ["status"])
    op.create_table(
        "action_plan_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("action_plans.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('consultant', 'assistant')", name="plan_message_role"),
    )

    op.add_column("settings", sa.Column("reminder_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("settings", sa.Column("reminder_after_days", sa.Integer(), nullable=False, server_default="21"))
    op.add_column("settings", sa.Column("reminder_auto_send", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("settings", sa.Column("hide_after_days", sa.Integer(), nullable=False, server_default="60"))


def downgrade() -> None:
    for column in ("hide_after_days", "reminder_auto_send", "reminder_after_days", "reminder_enabled"):
        op.drop_column("settings", column)
    op.drop_table("action_plan_messages")
    op.drop_index("ix_action_plans_status", table_name="action_plans")
    op.drop_table("action_plans")
    op.drop_table("customer_profiles")
    op.drop_column("bookings", "message")
    op.drop_index("ix_customers_consultant_id", table_name="customers")
    for column in ("reminder_sent_at", "notes", "siren", "company_name", "consultant_id"):
        op.drop_column("customers", column)
    op.drop_table("staff_users")
