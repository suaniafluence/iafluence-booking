"""End of session: close finished sessions and email the link to book the next one (or, after a free discovery
call, thanks and where to buy consulting hours).

Runs in the API process every `follow_up_poll_seconds`. Moving a booking from 'confirmed' to 'completed'
frees the purchase for its next booking (one upcoming session per purchase) and is the idempotency marker:
each finished session is processed once, even if several processes poll concurrently.

With session reports on (Fireflies + Codex configured), the email is not prepared here: a session report is
created instead, and app.services.session_reports prepares the email once the summary is written.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Booking
from app.services import notifications, session_reports
from app.services.email_service import Mailer

log = logging.getLogger(__name__)

# Sessions that ended longer ago than this (API down, first deploy…) are closed without an email.
EMAIL_GRACE = timedelta(hours=24)


def process_finished_sessions(mailer: Mailer, now: datetime) -> int:
    """Close every confirmed session that has ended; return how many follow-up emails were prepared (or deferred
    to a session report).

    Hours left -> link to book the next session. Last hour used -> thanks, with where to buy more hours.
    """
    to_notify: list[tuple[int, str]] = []
    to_thank: list[int] = []
    to_thank_prospect: list[int] = []
    reports = 0
    with SessionLocal() as db:
        with_reports = session_reports.enabled(db)
        finished = db.scalars(
            select(Booking)
            .where(Booking.status == "confirmed", Booking.end_datetime <= now)
            .order_by(Booking.end_datetime)
            .with_for_update(skip_locked=True)
        ).all()
        for booking in finished:
            booking.status = "completed"
            purchase = booking.purchase
            if purchase is not None and purchase.payment_status != "paid":
                continue
            if now - booking.end_datetime > EMAIL_GRACE:
                log.warning("booking %s ended at %s: closed without follow-up email", booking.id, booking.end_datetime)
                continue
            if booking.kind == "discovery":
                # Free call: a report when they are on, otherwise thanks and where to buy consulting hours.
                if with_reports:
                    session_reports.create_for(db, booking, now)
                    reports += 1
                else:
                    to_thank_prospect.append(booking.id)
                continue
            last = purchase.hours_remaining < 1
            token = None if last else notifications.active_token(db, purchase.id)
            if not last and token is None:
                continue
            if with_reports:
                session_reports.create_for(db, booking, now)
                reports += 1
            elif last:
                to_thank.append(purchase.id)
            else:
                to_notify.append((purchase.id, token))
        db.commit()
    # After the commit: a crash can lose an email, never send it twice.
    for purchase_id, token in to_notify:
        notifications.send_next_session_link(mailer, purchase_id, token)
    for purchase_id in to_thank:
        notifications.send_last_session_thanks(mailer, purchase_id)
    for booking_id in to_thank_prospect:
        notifications.send_discovery_thanks(mailer, booking_id)
    return len(to_notify) + len(to_thank) + len(to_thank_prospect) + reports


async def run_forever(mailer_factory: Callable[[], Mailer], interval_s: float) -> None:
    while True:
        try:
            await asyncio.to_thread(process_finished_sessions, mailer_factory(), datetime.now(UTC))
        except Exception:
            log.exception("end-of-session job failed")
        await asyncio.sleep(interval_s)
