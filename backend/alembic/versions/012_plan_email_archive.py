"""Action plans: Gmail draft of the validated plan, and archiving so a customer can have a next plan

Revision ID: 012
Revises: 011
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_plans", sa.Column("email_drafted_at", sa.DateTime(timezone=True)))
    op.add_column("action_plans", sa.Column("archived_at", sa.DateTime(timezone=True)))
    # One plan per customer becomes one *active* plan per customer: archived ones are kept as history.
    op.drop_constraint("action_plans_customer_id_key", "action_plans", type_="unique")
    op.create_index(
        "uq_action_plans_active",
        "action_plans",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_action_plans_active", table_name="action_plans")
    op.execute("DELETE FROM action_plans WHERE archived_at IS NOT NULL")
    op.create_unique_constraint("action_plans_customer_id_key", "action_plans", ["customer_id"])
    op.drop_column("action_plans", "archived_at")
    op.drop_column("action_plans", "email_drafted_at")
