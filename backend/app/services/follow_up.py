"""End of session: close finished sessions and email the link to book the next one.

Runs in the API process every `follow_up_poll_seconds`. Moving a booking from 'confirmed' to 'completed'
frees the purchase for its next booking (one upcoming session per purchase) and is the idempotency marker:
each finished session is processed once, even if several processes poll concurrently.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Booking
from app.services import notifications
from app.services.email_service import Mailer

log = logging.getLogger(__name__)

# Sessions that ended longer ago than this (API down, first deploy…) are closed without an email.
EMAIL_GRACE = timedelta(hours=24)


def process_finished_sessions(mailer: Mailer, now: datetime) -> int:
    """Close every confirmed session that has ended; return how many follow-up emails were prepared.

    Hours left -> link to book the next session. Last hour used -> thanks, with where to buy more hours.
    """
    to_notify: list[tuple[int, str]] = []
    to_thank: list[int] = []
    with SessionLocal() as db:
        finished = db.scalars(
            select(Booking)
            .where(Booking.status == "confirmed", Booking.end_datetime <= now)
            .order_by(Booking.end_datetime)
            .with_for_update(skip_locked=True)
        ).all()
        for booking in finished:
            booking.status = "completed"
            purchase = booking.purchase
            if purchase.payment_status != "paid":
                continue
            if now - booking.end_datetime > EMAIL_GRACE:
                log.warning("booking %s ended at %s: closed without follow-up email", booking.id, booking.end_datetime)
                continue
            if purchase.hours_remaining < 1:
                to_thank.append(purchase.id)
                continue
            token = notifications.active_token(db, purchase.id)
            if token is not None:
                to_notify.append((purchase.id, token))
        db.commit()
    # After the commit: a crash can lose an email, never send it twice.
    for purchase_id, token in to_notify:
        notifications.send_next_session_link(mailer, purchase_id, token)
    for purchase_id in to_thank:
        notifications.send_last_session_thanks(mailer, purchase_id)
    return len(to_notify) + len(to_thank)


async def run_forever(mailer_factory: Callable[[], Mailer], interval_s: float) -> None:
    while True:
        try:
            await asyncio.to_thread(process_finished_sessions, mailer_factory(), datetime.now(UTC))
        except Exception:
            log.exception("end-of-session job failed")
        await asyncio.sleep(interval_s)
