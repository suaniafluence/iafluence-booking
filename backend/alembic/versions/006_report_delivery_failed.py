"""Session reports whose Gmail email failed: delivery "failed", so the admin can prepare it again

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

GMAIL_FAILED = "L'email n'a pas pu être préparé dans Gmail (voir les logs de l'API)."


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE session_reports SET delivery = 'failed' WHERE status = 'drafted' AND error = :error"),
        {"error": GMAIL_FAILED},
    )


def downgrade() -> None:
    op.execute("UPDATE session_reports SET delivery = 'draft' WHERE delivery = 'failed'")
