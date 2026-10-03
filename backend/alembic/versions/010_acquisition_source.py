"""How each customer came (website, WhatsApp, recommendation…), and clients added by hand without a purchase

Revision ID: 010
Revises: 009
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("acquisition_source", sa.String(32)))
    op.add_column("customers", sa.Column("acquisition_detail", sa.String(255)))
    # Customers who paid or booked a call on the website came from it; the others stay unknown.
    op.execute(
        "UPDATE customers SET acquisition_source = 'site' WHERE id IN ("
        "SELECT customer_id FROM purchases WHERE product_id <> 'manual' "
        "UNION SELECT customer_id FROM bookings WHERE kind = 'discovery')"
    )


def downgrade() -> None:
    op.drop_column("customers", "acquisition_detail")
    op.drop_column("customers", "acquisition_source")
