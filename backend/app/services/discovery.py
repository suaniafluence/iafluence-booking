"""Free discovery call, booked by anyone from /{lang}/decouverte (replaces the Google appointment page).

Same weekly hours, notice, horizon and buffers as the paid sessions, a shorter duration (settings), and the same
double-booking protection (booking lock, fresh free/busy, exclusion constraint). Nothing is paid, so abuse is kept
in check by one upcoming call per email (unique index), a per-IP rate limit and a honeypot field (public router).
At the end of the call, the session report pipeline prepares the follow-up email (app.services.session_reports).
"""

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import i18n
from app.auth import default_consultant_id
from app.models import Booking, Customer, Settings
from app.services import settings_service
from app.services.availability import Interval, SlotRules, resolve_slot
from app.services.booking_service import BOOKING_LOCK_KEY, BookingError, SlotInvalid, list_availability, reserve
from app.services.calendar_service import CalendarGateway

log = logging.getLogger(__name__)


class DiscoveryClosed(BookingError):
    status_code, code, message = 404, "discovery_closed", "Les appels découverte ne sont pas ouverts pour le moment."


class DiscoveryRejected(BookingError):
    status_code, code, message = 400, "rejected", "Demande refusée."


class TooManyAttempts(BookingError):
    status_code, code, message = 429, "too_many_attempts", "Trop de tentatives. Réessayez dans une heure."


class DiscoveryAlreadyBooked(BookingError):
    status_code, code, message = (
        409,
        "discovery_already_booked",
        "Un appel découverte est déjà prévu pour cette adresse email : retrouvez-le dans l’email de confirmation.",
    )


def open_settings(db: Session) -> Settings:
    settings = settings_service.get_settings(db)
    if not settings.discovery_enabled:
        raise DiscoveryClosed()
    return settings


def slot_rules(db: Session, settings: Settings) -> SlotRules:
    """The sessions' rules, with the call's duration as both length and step (09:00, 09:30, 10:00…)."""
    duration = timedelta(minutes=settings.discovery_duration_min)
    return replace(settings_service.slot_rules(db, settings), duration=duration, step=duration)


def availability(
    db: Session, calendar: CalendarGateway, now: datetime, frm: datetime | None = None, to: datetime | None = None
) -> list[Interval]:
    settings = open_settings(db)
    return list_availability(db, calendar, now, frm, to, rules=slot_rules(db, settings))


def _customer(db: Session, name: str, email: str) -> Customer:
    """Existing customers keep their name: anyone can type an email on a public form."""
    db.execute(
        pg_insert(Customer)
        .values(name=name, email=email, consultant_id=default_consultant_id(db), acquisition_source="site")
        .on_conflict_do_nothing(index_elements=[Customer.email])
    )
    return db.scalar(select(Customer).where(Customer.email == email))


def book(
    db: Session,
    calendar: CalendarGateway,
    *,
    name: str,
    email: str,
    start: datetime,
    now: datetime,
    message: str | None = None,
    locale: str | None = None,
    customer_timezone: str | None = None,
) -> Booking:
    settings = open_settings(db)
    rules = slot_rules(db, settings)
    slot = resolve_slot(rules, now, start)  # never trust the client-provided time
    if slot is None:
        raise SlotInvalid()

    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": BOOKING_LOCK_KEY})
    customer = _customer(db, name, email)
    upcoming = db.scalar(
        select(Booking.id).where(
            Booking.customer_id == customer.id, Booking.kind == "discovery", Booking.status == "confirmed"
        )
    )
    if upcoming is not None:
        db.rollback()
        raise DiscoveryAlreadyBooked()

    locale = i18n.normalize_locale(locale) or i18n.DEFAULT_LOCALE
    customer_timezone = i18n.valid_timezone(customer_timezone)
    description = i18n.text(locale, "discovery_event_description", minutes=settings.discovery_duration_min)
    if message:
        description += "\n\n" + i18n.text(locale, "discovery_event_message", message=message)
    if customer_timezone and customer_timezone != settings.timezone:
        description += "\n\n" + i18n.text(locale, "event_timezone", tz=customer_timezone)
    booking = reserve(
        db,
        calendar,
        settings,
        rules,
        slot,
        Booking(
            kind="discovery",
            customer_id=customer.id,
            locale=locale,
            customer_timezone=customer_timezone,
            message=message or None,
        ),
        summary=i18n.text(locale, "discovery_event_summary", name=name),
        description=description,
        attendee=customer,
    )
    log.info("discovery call %s booked", booking.id)
    return booking
