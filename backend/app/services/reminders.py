"""Inactivity reminder: a learner without a session for `reminder_after_days` gets one email per idle period.

- hours left to book -> « il vous reste X h » with their booking link;
- programme finished -> how it is going, and where to buy more hours (SHOP_URL);
- discovery call but no purchase -> follow-up of the call, and where to buy hours.
Gmail draft for the consultant to review, unless `reminder_auto_send` is on. Nobody idle for `hide_after_days` or
more is written to (first deploy, long-gone customers). `reminder_sent_at` later than the last activity means
this period was handled; the next session or purchase opens a new one.
Runs with the end-of-session job; emails leave after the commit (a crash can lose one, never send it twice).
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_config
from app.db import SessionLocal
from app.i18n import text
from app.models import Booking, Customer
from app.services import formatting as fmt
from app.services import learners, notifications
from app.services.email_service import Mailer, render, send_safely
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reminder:
    to: str
    subject: str
    body: str
    as_draft: bool


def _locale(customer: Customer, bookings: list[Booking]) -> str:
    purchases = sorted(customer.purchases, key=lambda p: p.created_at)
    if purchases:
        return purchases[-1].locale
    return next((b.locale for b in reversed(bookings) if b.locale), "fr")


def compose(db: Session, customer: Customer, bookings: list[Booking], act: learners.Activity) -> Reminder | None:
    settings = get_settings(db)
    locale = _locale(customer, bookings)
    common = {"name": customer.name, "consultant_name": settings.consultant_name}
    if act.status == "en_cours" and act.hours_to_schedule > 0:
        purchase = next((p for p in act.paid if p.hours_remaining > 0), None)
        token = notifications.active_token(db, purchase.id) if purchase else None
        if token is None:
            return None
        body = render(
            f"{locale}/reminder_session.txt",
            **common,
            hours_remaining=act.hours_to_schedule,
            hours_remaining_label=fmt.hours(act.hours_to_schedule, locale),
            booking_url=notifications.booking_url(token, locale),
        )
        subject = text(locale, "subject_reminder_session")
    elif act.status == "termine":
        body = render(f"{locale}/reminder_rebook.txt", **common, shop_url=get_config().shop_url)
        subject = text(locale, "subject_reminder_rebook")
    elif act.status == "prospect" and any(b.kind == "discovery" and b.status == "completed" for b in bookings):
        body = render(f"{locale}/reminder_prospect.txt", **common, shop_url=get_config().shop_url)
        subject = text(locale, "subject_reminder_prospect")
    else:
        return None
    return Reminder(customer.email, subject, body, as_draft=not settings.reminder_auto_send)


def due(customer: Customer, act: learners.Activity, after_days: int, hide_days: int) -> bool:
    if act.idle_days is None or not (after_days <= act.idle_days < hide_days):
        return False
    return not (customer.reminder_sent_at and act.last_activity and customer.reminder_sent_at >= act.last_activity)


def process(mailer: Mailer, now: datetime) -> int:
    reminders: list[Reminder] = []
    with SessionLocal() as db:
        settings = get_settings(db)
        if not settings.reminder_enabled:
            return 0
        customers = db.scalars(
            select(Customer).options(selectinload(Customer.purchases)).with_for_update(skip_locked=True, of=Customer)
        ).all()
        bookings: dict[int, list[Booking]] = {c.id: [] for c in customers}
        for b in db.scalars(
            select(Booking)
            .options(selectinload(Booking.purchase))
            .where(Booking.customer_id.in_(list(bookings)))
            .order_by(Booking.start_datetime)
        ):
            bookings[b.customer_id].append(b)
        for customer in customers:
            act = learners.activity(customer, bookings[customer.id], now)
            if not due(customer, act, settings.reminder_after_days, settings.hide_after_days):
                continue
            # Handled for this idle period, even when there is nothing to say (refund, link revoked).
            customer.reminder_sent_at = now
            if reminder := compose(db, customer, bookings[customer.id], act):
                reminders.append(reminder)
        db.commit()
    for r in reminders:
        send_safely(mailer, r.to, r.subject, r.body, as_draft=r.as_draft)
    if reminders:
        log.info("%d inactivity reminder(s) prepared", len(reminders))
    return len(reminders)
