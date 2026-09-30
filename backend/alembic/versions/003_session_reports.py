"""session reports (Fireflies transcript -> Codex summary -> Gmail draft) and Codex device login

Revision ID: 003
Revises: 002
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("bookings.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("transcript_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("claimed_until", sa.DateTime(timezone=True)),
        sa.Column("fireflies_transcript_id", sa.String(128)),
        sa.Column("summary", postgresql.JSONB),
        sa.Column("image_png", sa.LargeBinary),
        sa.Column("error", sa.Text),
        sa.Column("delivery", sa.String(16)),
        sa.Column("with_summary", sa.Boolean),
        sa.Column("drafted_at", sa.DateTime(timezone=True)),
        sa.Column("erased_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('waiting_transcript', 'summarizing', 'ready', 'drafted', 'failed')", name="report_status"
        ),
    )
    op.create_index("ix_session_reports_status_next_attempt", "session_reports", ["status", "next_attempt_at"])

    op.create_table(
        "codex_logins",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("login_id", sa.String(128), nullable=False),
        sa.Column("verification_url", sa.String(512), nullable=False),
        sa.Column("user_code", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'EXPIRED', 'DENIED', 'CANCELLED', 'ERROR')", name="codex_login_status"
        ),
    )

    op.add_column(
        "settings",
        sa.Column("send_reports_without_review", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("settings", "send_reports_without_review")
    op.drop_table("codex_logins")
    op.drop_index("ix_session_reports_status_next_attempt", table_name="session_reports")
    op.drop_table("session_reports")
