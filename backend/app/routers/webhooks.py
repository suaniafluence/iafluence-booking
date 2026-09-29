import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.deps import get_mailer, get_stripe
from app.models import StripeEvent
from app.services import notifications, stripe_service

log = logging.getLogger(__name__)
router = APIRouter()

FULFILL_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    background: BackgroundTasks,
    stripe_gw=Depends(get_stripe),
    mailer=Depends(get_mailer),
):
    payload = await request.body()
    try:
        event = stripe_gw.construct_event(payload, request.headers.get("stripe-signature"))
    except Exception:
        log.warning("stripe webhook rejected: bad payload or signature")
        raise HTTPException(400, "invalid signature")
    return await run_in_threadpool(_process_event, event, stripe_gw, mailer, background)


def _process_event(event: dict[str, Any], stripe_gw, mailer, background: BackgroundTasks) -> dict:
    event_id, event_type = event["id"], event["type"]
    obj = event["data"]["object"]
    with SessionLocal() as db:
        if db.get(StripeEvent, event_id) is not None:
            return {"status": "duplicate"}

        note = None
        if event_type in FULFILL_EVENTS:
            try:
                result = stripe_service.fulfill_checkout(db, stripe_gw, obj["id"])
                if result.created:
                    background.add_task(notifications.send_booking_link, mailer, result.purchase.id, result.token)
            except stripe_service.PaymentInvalid as exc:
                # e.g. async payment still pending, or a product unrelated to booking.
                note = f"ignored: {exc}"
                log.info("checkout %s not fulfilled: %s", obj.get("id"), exc)
        elif event_type == "charge.refunded":
            purchase = stripe_service.handle_refund(db, obj)
            if purchase is not None:
                background.add_task(notifications.send_refund_alert, mailer, purchase.id, bool(obj.get("refunded")))
            else:
                note = "no matching purchase"
        else:
            note = "logged only"

        # Recorded only after successful processing, so a failure makes Stripe retry.
        db.execute(
            pg_insert(StripeEvent)
            .values(event_id=event_id, type=event_type, note=note)
            .on_conflict_do_nothing(index_elements=[StripeEvent.event_id])
        )
        db.commit()
    return {"status": "ok"}
