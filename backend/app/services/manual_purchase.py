"""Clients added by hand from the admin area (paid outside the website: transfer, invoice, offered hours…)."""

import logging
import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import BookingToken, Purchase
from app.services import tokens
from app.services.stripe_service import upsert_customer

log = logging.getLogger(__name__)

MANUAL_PRODUCT_ID = "manual"


@dataclass(frozen=True)
class ManualPurchase:
    purchase: Purchase
    token: str


def create(db: Session, *, name: str, email: str, hours: int, product_name: str, amount_cents: int) -> ManualPurchase:
    customer = upsert_customer(db, name, email)
    purchase = Purchase(
        customer_id=customer.id,
        # Not a Stripe session: a unique placeholder keeps the column's uniqueness and makes the origin obvious.
        stripe_checkout_session_id=f"manual_{secrets.token_hex(12)}",
        stripe_payment_id=None,
        product_id=MANUAL_PRODUCT_ID,
        product_name=product_name,
        amount_cents=amount_cents,
        currency="eur",
        hours_purchased=hours,
        hours_booked=0,
        payment_status="paid",
    )
    db.add(purchase)
    db.flush()
    token = tokens.new_token()
    db.add(BookingToken(purchase_id=purchase.id, token=token))
    db.commit()
    db.refresh(purchase)
    log.info("manual purchase %s created (%s h)", purchase.id, hours)
    return ManualPurchase(purchase, token)
