"""Transcripts pasted by the consultant (phone dictation, no speaker names), attributed to speakers by Codex

Revision ID: 011
Revises: 010
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_reports", sa.Column("transcript_source", sa.String(16), server_default="fireflies", nullable=False)
    )
    op.add_column("session_reports", sa.Column("pasted_transcript", sa.Text()))
    op.add_column("session_reports", sa.Column("speaker_hint", JSONB))
    op.add_column("session_reports", sa.Column("speakers", JSONB))
    op.create_check_constraint(
        "report_transcript_source", "session_reports", "transcript_source IN ('fireflies', 'pasted')"
    )


def downgrade() -> None:
    op.drop_constraint("report_transcript_source", "session_reports", type_="check")
    op.drop_column("session_reports", "speakers")
    op.drop_column("session_reports", "speaker_hint")
    op.drop_column("session_reports", "pasted_transcript")
    op.drop_column("session_reports", "transcript_source")
