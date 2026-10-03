"""Stripe payment verification and purchase fulfilment.

`fulfill_checkout` is idempotent: the webhook and the post-payment redirect may both
call it, in any order, and exactly one purchase + one booking token is created.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_config
from app.i18n import checkout_locale
from app.models import BookingToken, Customer, Purchase
from app.services import tokens

log = logging.getLogger(__name__)

MAX_HOURS = 50


class PaymentInvalid(Exception):
    """The checkout session cannot give access to booking (unpaid, unknown product…)."""


class StripeGateway(Protocol):
    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]: ...

    def construct_event(self, payload: bytes, signature: str | None) -> dict[str, Any]: ...


class LiveStripeGateway:
    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        import stripe

        try:
            session = stripe.checkout.Session.retrieve(
                session_id,
                expand=["line_items.data.price.product"],
                api_key=get_config().stripe_secret_key,
            )
        except stripe.InvalidRequestError as exc:  # unknown / malformed session id
            raise PaymentInvalid("unknown checkout session") from exc
        return session.to_dict()

    def construct_event(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        import stripe

        event = stripe.Webhook.construct_event(payload, signature, get_config().stripe_webhook_secret)
        return event.to_dict()


@dataclass(frozen=True)
class CheckoutInfo:
    session_id: str
    payment_intent_id: str | None
    email: str
    name: str
    amount_cents: int
    currency: str
    product_id: str
    product_name: str
    hours: int
    locale: str


def _as_id(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("id")
    return value


def parse_checkout(session: dict[str, Any]) -> CheckoutInfo:
    """Validate a (expanded) Checkout Session and extract what booking needs."""
    if session.get("payment_status") != "paid":
        raise PaymentInvalid("payment not completed")

    details = session.get("customer_details") or {}
    email = (details.get("email") or session.get("customer_email") or "").strip().lower()
    if not email:
        raise PaymentInvalid("no customer email")

    allowed = get_config().allowed_product_ids
    hours = 0
    product_id = product_name = None
    for item in (session.get("line_items") or {}).get("data", []):
        product = (item.get("price") or {}).get("product")
        if not isinstance(product, dict):
            continue
        if allowed and product.get("id") not in allowed:
            continue
        raw = (product.get("metadata") or {}).get("hours")
        try:
            h = int(raw)
        except (TypeError, ValueError):
            continue
        if h <= 0:
            continue
        hours += h * int(item.get("quantity") or 1)
        product_id = product_id or product["id"]
        product_name = product_name or product.get("name") or item.get("description") or "Conseil IA"

    if not hours or product_id is None:
        raise PaymentInvalid("no eligible product in checkout session")
    if hours > MAX_HOURS:
        raise PaymentInvalid("unexpected hours quantity")

    return CheckoutInfo(
        session_id=session["id"],
        payment_intent_id=_as_id(session.get("payment_intent")),
        email=email,
        name=(details.get("name") or "").strip() or email,
        amount_cents=int(session.get("amount_total") or 0),
        currency=(session.get("currency") or "eur").lower(),
        product_id=product_id,
        product_name=product_name,
        hours=hours,
        locale=checkout_locale(session),
    )


@dataclass(frozen=True)
class FulfillResult:
    purchase: Purchase
    token: str
    created: bool


def upsert_customer(db: Session, name: str, email: str) -> Customer:
    """Email is the identity; the latest name wins."""
    from app.auth import default_consultant_id

    db.execute(
        pg_insert(Customer)
        .values(name=name, email=email, consultant_id=default_consultant_id(db))
        .on_conflict_do_update(index_elements=[Customer.email], set_={"name": name})
    )
    return db.scalar(select(Customer).where(Customer.email == email).execution_options(populate_existing=True))


def fulfill_checkout(db: Session, stripe_gw: StripeGateway, session_id: str) -> FulfillResult:
    existing = db.scalar(select(Purchase).where(Purchase.stripe_checkout_session_id == session_id))
    if existing is not None:
        return FulfillResult(existing, _active_token(db, existing), created=False)

    info = parse_checkout(stripe_gw.retrieve_checkout_session(session_id))

    customer = upsert_customer(db, info.name, info.email)

    inserted_id = db.scalar(
        pg_insert(Purchase)
        .values(
            customer_id=customer.id,
            stripe_checkout_session_id=info.session_id,
            stripe_payment_id=info.payment_intent_id,
            product_id=info.product_id,
            product_name=info.product_name,
            amount_cents=info.amount_cents,
            currency=info.currency,
            hours_purchased=info.hours,
            hours_booked=0,
            payment_status="paid",
            locale=info.locale,
        )
        .on_conflict_do_nothing(index_elements=[Purchase.stripe_checkout_session_id])
        .returning(Purchase.id)
    )
    if inserted_id is None:  # lost the race against a concurrent call
        db.commit()
        purchase = db.scalar(select(Purchase).where(Purchase.stripe_checkout_session_id == session_id))
        return FulfillResult(purchase, _active_token(db, purchase), created=False)

    token = tokens.new_token()
    db.add(BookingToken(purchase_id=inserted_id, token=token))
    db.commit()
    purchase = db.get(Purchase, inserted_id)
    log.info("purchase %s created for checkout session", purchase.id)
    plan_after_purchase(db, purchase)
    return FulfillResult(purchase, token, created=True)


def plan_after_purchase(db: Session, purchase: Purchase) -> None:
    """Hours bought after a discovery call: Codex drafts the consultant's action plan (app.services.action_plans)."""
    from app.services import action_plans

    try:
        action_plans.on_purchase(db, purchase, datetime.now(UTC))
    except Exception:
        # Never in the way of a payment.
        db.rollback()
        log.exception("could not queue the action plan of purchase %s", purchase.id)


def _active_token(db: Session, purchase: Purchase) -> str:
    tok = db.scalar(
        select(BookingToken)
        .where(BookingToken.purchase_id == purchase.id, BookingToken.revoked_at.is_(None))
        .order_by(BookingToken.id.desc())
    )
    if tok is None or purchase.payment_status != "paid":
        raise PaymentInvalid("booking access revoked")
    return tok.token


def handle_refund(db: Session, charge: dict[str, Any]) -> Purchase | None:
    """Full refund -> purchase refunded and every booking token revoked."""
    pi = _as_id(charge.get("payment_intent"))
    if not pi:
        return None
    purchase = db.scalar(select(Purchase).where(Purchase.stripe_payment_id == pi))
    if purchase is None:
        return None
    if not charge.get("refunded"):  # partial refund: keep access, admin is notified
        return purchase
    purchase.payment_status = "refunded"
    now = datetime.now(UTC)
    for tok in db.scalars(
        select(BookingToken).where(BookingToken.purchase_id == purchase.id, BookingToken.revoked_at.is_(None))
    ):
        tok.revoked_at = now
    db.commit()
    return purchase
