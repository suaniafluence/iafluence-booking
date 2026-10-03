"""Clients added by hand from the admin area (paid outside the website: transfer, invoice, offered hours…)."""

import logging
import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import BookingToken, Customer, Purchase
from app.services import tokens
from app.services.stripe_service import plan_after_purchase, upsert_customer

log = logging.getLogger(__name__)

MANUAL_PRODUCT_ID = "manual"


@dataclass(frozen=True)
class ManualClient:
    customer: Customer
    purchase: Purchase | None
    token: str | None


def create(
    db: Session,
    *,
    name: str,
    email: str,
    acquisition_source: str,
    acquisition_detail: str | None,
    hours: int | None,
    product_name: str,
    amount_cents: int,
) -> ManualClient:
    """Without hours the client is only added to the follow-up (a prospect): no purchase, no booking link."""
    customer = upsert_customer(db, name, email)
    # Said by the consultant: it wins over what was known.
    customer.acquisition_source = acquisition_source
    customer.acquisition_detail = acquisition_detail or None
    if hours is None:
        db.commit()
        log.info("customer %s added by hand without a purchase", customer.id)
        return ManualClient(customer, None, None)
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
    plan_after_purchase(db, purchase)
    return ManualClient(customer, purchase, token)
