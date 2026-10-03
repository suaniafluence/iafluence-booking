"""Confidentiality agreement (NDA): the signed PDF uploaded by the admin, and its exchange with each customer

Revision ID: 008
Revises: 007
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nda_documents",
        sa.Column("locale", sa.String(5), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("locale IN ('fr', 'en', 'es')", name="nda_locale"),
    )
    op.add_column("customers", sa.Column("nda_sent_at", sa.DateTime(timezone=True)))
    op.add_column("customers", sa.Column("nda_signed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("customers", "nda_signed_at")
    op.drop_column("customers", "nda_sent_at")
    op.drop_table("nda_documents")
