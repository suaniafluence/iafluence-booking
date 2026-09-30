"""Availability listing and booking with double-booking protection (R06, R10)."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Booking, BookingToken, Purchase, Settings
from app.services import settings_service
from app.services.availability import (
    Interval,
    available_slots,
    booking_window,
    busy_query_range,
    is_free,
    resolve_slot,
)
from app.services.calendar_service import (
    CalendarGateway,
    CalendarUnavailable,
    CalendarWriteError,
    freebusy_cache,
)

log = logging.getLogger(__name__)

# Arbitrary constant key for pg_advisory_xact_lock: serialises all bookings (single consultant).
BOOKING_LOCK_KEY = 0x1AF1_0E0C

SLOT_TAKEN_MESSAGE = (
    "Ce créneau vient d’être réservé ou n’est plus disponible. Veuillez choisir un autre horaire."
)


class BookingError(Exception):
    status_code = 400
    code = "booking_error"
    message = "Réservation impossible."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message


class InvalidToken(BookingError):
    status_code, code, message = 404, "invalid_token", "Ce lien de réservation est invalide ou a expiré."


@dataclass(frozen=True)
class BookedSlot:
    start_datetime: datetime
    end_datetime: datetime
    meet_url: str | None


class AlreadyBooked(BookingError):
    status_code, code, message = 409, "already_booked", "Votre prochaine session est déjà réservée."

    def __init__(self, booking: Booking):
        super().__init__()
        # Copied now: the ORM instance is expired by a rollback and detached once the request session closes.
        self.booking = BookedSlot(booking.start_datetime, booking.end_datetime, booking.meet_url)


class NoHoursLeft(BookingError):
    status_code, code, message = 409, "no_hours_left", "Toutes vos heures ont déjà été planifiées."


class SlotInvalid(BookingError):
    status_code, code, message = 422, "slot_invalid", "Ce créneau n’est pas proposé à la réservation."


class SlotTaken(BookingError):
    status_code, code, message = 409, "slot_taken", SLOT_TAKEN_MESSAGE


class CalendarDown(BookingError):
    status_code, code, message = (
        503,
        "calendar_unavailable",
        "Les disponibilités sont momentanément indisponibles. Veuillez réessayer dans quelques minutes.",
    )


class CalendarWriteFailed(BookingError):
    status_code, code, message = (
        502,
        "calendar_write_failed",
        "Le rendez-vous n’a pas pu être créé. Veuillez réessayer.",
    )


def resolve_token(db: Session, token: str) -> BookingToken:
    tok = db.scalar(select(BookingToken).where(BookingToken.token == token))
    if tok is None or tok.revoked_at is not None or tok.purchase.payment_status != "paid":
        raise InvalidToken()
    return tok


def confirmed_booking(db: Session, purchase_id: int) -> Booking | None:
    return db.scalar(
        select(Booking).where(Booking.purchase_id == purchase_id, Booking.status == "confirmed")
    )


def db_busy(db: Session, rng: Interval) -> list[Interval]:
    """Confirmed bookings — covers the gap before Google free/busy reflects a new event."""
    rows = db.execute(
        select(Booking.start_datetime, Booking.end_datetime).where(
            Booking.status == "confirmed",
            Booking.start_datetime < rng.end,
            Booking.end_datetime > rng.start,
        )
    )
    return [Interval(s, e) for s, e in rows]


def list_availability(
    db: Session,
    calendar: CalendarGateway,
    now: datetime,
    frm: datetime | None = None,
    to: datetime | None = None,
) -> list[Interval]:
    settings = settings_service.get_settings(db)
    rules = settings_service.slot_rules(db, settings)
    window = booking_window(rules, now, frm, to)
    if window.start >= window.end:
        return []
    rng = busy_query_range(window, rules)
    try:
        busy = freebusy_cache.get(calendar, settings_service.busy_calendar_ids(db, settings), rng.start, rng.end)
    except CalendarUnavailable:
        log.exception("free/busy unavailable")
        raise CalendarDown()
    return available_slots(rules, now, busy + db_busy(db, rng), frm, to)


def _event_description(purchase: Purchase, hours_remaining: int) -> str:
    return (
        "Session de conseil IA.\n\n"
        f"Heures achetées : {purchase.hours_purchased} h\n"
        "Session réservée : 1 h\n"
        f"Heures restantes : {hours_remaining} h\n\n"
        "Paiement Stripe :\n"
        f"{purchase.stripe_payment_id or purchase.stripe_checkout_session_id}"
    )


def book(db: Session, calendar: CalendarGateway, token: str, start: datetime, now: datetime) -> Booking:
    tok = resolve_token(db, token)
    purchase_id = tok.purchase_id

    existing = confirmed_booking(db, purchase_id)
    if existing is not None:
        raise AlreadyBooked(existing)
    if tok.purchase.hours_remaining < 1:
        raise NoHoursLeft()

    settings: Settings = settings_service.get_settings(db)
    rules = settings_service.slot_rules(db, settings)
    slot = resolve_slot(rules, now, start)  # never trust the client-provided time
    if slot is None:
        raise SlotInvalid()

    # --- critical section: one booking at a time --------------------------------
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": BOOKING_LOCK_KEY})
    purchase = db.scalar(
        select(Purchase).where(Purchase.id == purchase_id).with_for_update().execution_options(populate_existing=True)
    )
    existing = confirmed_booking(db, purchase_id)
    if existing is not None:
        exc = AlreadyBooked(existing)
        db.rollback()
        raise exc
    if purchase.payment_status != "paid" or purchase.hours_remaining < 1:
        db.rollback()
        raise InvalidToken() if purchase.payment_status != "paid" else NoHoursLeft()

    # R06 — fresh free/busy check (no cache) right before creating the event.
    padded = Interval(slot.start - rules.buffer_before, slot.end + rules.buffer_after)
    try:
        busy = calendar.free_busy(settings_service.busy_calendar_ids(db, settings), padded.start, padded.end)
    except CalendarUnavailable:
        db.rollback()
        log.exception("free/busy unavailable during booking")
        raise CalendarDown()
    if not is_free(slot, busy + db_busy(db, padded), rules):
        db.rollback()
        raise SlotTaken()

    customer = purchase.customer
    hours_remaining_after = purchase.hours_remaining - 1
    try:
        event = calendar.create_event(
            settings.booking_calendar_id,
            summary=f"Conseil IA - {customer.name}",
            description=_event_description(purchase, hours_remaining_after),
            start=slot.start.astimezone(rules.tz),
            end=slot.end.astimezone(rules.tz),
            timezone=settings.timezone,
            attendee_email=customer.email,
            attendee_name=customer.name,
            with_meet=settings.meet_enabled,
        )
    except CalendarWriteError:
        db.rollback()
        log.exception("event creation failed")
        raise CalendarWriteFailed()

    booking = Booking(
        purchase_id=purchase.id,
        customer_id=customer.id,
        start_datetime=slot.start,
        end_datetime=slot.end,
        google_event_id=event.event_id,
        meet_url=event.meet_url,
        status="confirmed",
    )
    db.add(booking)
    purchase.hours_booked = Purchase.hours_booked + 1
    try:
        db.commit()
    except IntegrityError:
        # A DB constraint caught a conflict: undo the calendar side (compensation).
        db.rollback()
        _compensate(calendar, settings.booking_calendar_id, event.event_id)
        raise SlotTaken()
    except Exception:
        db.rollback()
        _compensate(calendar, settings.booking_calendar_id, event.event_id)
        raise
    freebusy_cache.clear()
    db.refresh(booking)
    db.refresh(purchase)
    log.info("booking %s confirmed for purchase %s", booking.id, purchase.id)
    return booking


def _compensate(calendar: CalendarGateway, calendar_id: str, event_id: str) -> None:
    try:
        calendar.delete_event(calendar_id, event_id)
    except Exception:
        log.exception("could not delete orphan event %s — remove it manually", event_id)


def hours_summary(purchase: Purchase) -> dict[str, int]:
    return {
        "hours_purchased": purchase.hours_purchased,
        "hours_booked": purchase.hours_booked,
        "hours_remaining": purchase.hours_remaining,
    }

