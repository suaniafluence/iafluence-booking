import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_calendar, get_mailer, get_now, get_stripe
from app.schemas import (
    AvailabilityOut,
    BookingConfirmedOut,
    BookingContextOut,
    BookingIn,
    BookingOut,
    CheckoutOut,
    CustomerOut,
    DiscoveryIn,
    DiscoveryInfoOut,
    DiscoveryOut,
    PurchaseOut,
    Slot,
)
from app.services import booking_service, discovery, notifications, stripe_service
from app.services.rate_limit import RateLimiter, client_ip
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Free discovery call: attempts per visitor address (a refused slot counts too).
discovery_limiter = RateLimiter(limit=10, window=timedelta(hours=1))


class CheckoutNotFound(booking_service.BookingError):
    status_code, code, message = 404, "payment_not_found", "Paiement introuvable ou non finalisé."


@router.get("/checkout/{session_id}", response_model=CheckoutOut)
def exchange_checkout(
    session_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    stripe_gw=Depends(get_stripe),
    mailer=Depends(get_mailer),
):
    """Post-payment redirect: verify the Checkout Session with Stripe, return the booking token."""
    if not session_id.startswith("cs_") or len(session_id) > 255:
        raise CheckoutNotFound()
    try:
        result = stripe_service.fulfill_checkout(db, stripe_gw, session_id)
    except stripe_service.PaymentInvalid as exc:
        log.info("checkout %s refused: %s", session_id, exc)
        raise CheckoutNotFound()
    if result.created:
        background.add_task(notifications.send_booking_link, mailer, result.purchase.id, result.token)
    return CheckoutOut(token=result.token, locale=result.purchase.locale)


def _booking_out(booking, tz: str) -> BookingOut:
    z = ZoneInfo(tz)
    return BookingOut(
        start=booking.start_datetime.astimezone(z), end=booking.end_datetime.astimezone(z), meet_url=booking.meet_url
    )


@router.get("/booking/{token}", response_model=BookingContextOut)
def booking_context(token: str, db: Session = Depends(get_db)):
    tok = booking_service.resolve_token(db, token)
    purchase = tok.purchase
    settings = get_settings(db)
    existing = booking_service.confirmed_booking(db, purchase.id)
    return BookingContextOut(
        customer=CustomerOut(name=purchase.customer.name, email=purchase.customer.email),
        purchase=PurchaseOut(product_name=purchase.product_name, **booking_service.hours_summary(purchase)),
        booking=_booking_out(existing, settings.timezone) if existing else None,
        consultant_name=settings.consultant_name,
        timezone=settings.timezone,
        booking_duration_min=settings.booking_duration_min,
        locale=purchase.locale,
    )


@router.get("/availability", response_model=AvailabilityOut)
def availability(
    token: str,
    frm: AwareDatetime | None = Query(None, alias="from"),
    to: AwareDatetime | None = None,
    db: Session = Depends(get_db),
    calendar=Depends(get_calendar),
    now: datetime = Depends(get_now),
):
    tok = booking_service.resolve_token(db, token)
    if booking_service.confirmed_booking(db, tok.purchase_id) is not None:
        return AvailabilityOut(slots=[])
    tz = ZoneInfo(get_settings(db).timezone)
    slots = booking_service.list_availability(db, calendar, now, frm, to)
    # Only start/end ever leave the server (R05).
    return AvailabilityOut(slots=[Slot(start=s.start.astimezone(tz), end=s.end.astimezone(tz)) for s in slots])


@router.post("/bookings", response_model=BookingConfirmedOut, status_code=201)
def create_booking(
    body: BookingIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    calendar=Depends(get_calendar),
    mailer=Depends(get_mailer),
    now: datetime = Depends(get_now),
):
    booking = booking_service.book(db, calendar, body.token, body.start, now, body.locale, body.timezone)
    background.add_task(notifications.send_booking_confirmations, mailer, booking.id)
    tz = ZoneInfo(get_settings(db).timezone)
    return BookingConfirmedOut(
        status="confirmed",
        start=booking.start_datetime.astimezone(tz),
        end=booking.end_datetime.astimezone(tz),
        meet_url=booking.meet_url,
        **booking_service.hours_summary(booking.purchase),
    )


# --- free discovery call ------------------------------------------------------------------------------------------


@router.get("/discovery", response_model=DiscoveryInfoOut)
def discovery_info(db: Session = Depends(get_db)):
    settings = discovery.open_settings(db)
    return DiscoveryInfoOut(
        consultant_name=settings.consultant_name,
        timezone=settings.timezone,
        duration_min=settings.discovery_duration_min,
    )


@router.get("/discovery/availability", response_model=AvailabilityOut)
def discovery_availability(
    frm: AwareDatetime | None = Query(None, alias="from"),
    to: AwareDatetime | None = None,
    db: Session = Depends(get_db),
    calendar=Depends(get_calendar),
    now: datetime = Depends(get_now),
):
    slots = discovery.availability(db, calendar, now, frm, to)
    tz = ZoneInfo(get_settings(db).timezone)
    return AvailabilityOut(slots=[Slot(start=s.start.astimezone(tz), end=s.end.astimezone(tz)) for s in slots])


@router.post("/discovery", response_model=DiscoveryOut, status_code=201)
def book_discovery(
    body: DiscoveryIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    calendar=Depends(get_calendar),
    mailer=Depends(get_mailer),
    now: datetime = Depends(get_now),
):
    if body.website:
        raise discovery.DiscoveryRejected()
    if not discovery_limiter.hit(client_ip(request), now):
        raise discovery.TooManyAttempts()
    booking = discovery.book(
        db,
        calendar,
        name=body.name,
        email=str(body.email).lower(),
        start=body.start,
        now=now,
        message=body.message or None,
        locale=body.locale,
        customer_timezone=body.timezone,
    )
    background.add_task(notifications.send_discovery_confirmations, mailer, booking.id, body.message or None)
    tz = ZoneInfo(get_settings(db).timezone)
    return DiscoveryOut(
        start=booking.start_datetime.astimezone(tz), end=booking.end_datetime.astimezone(tz), meet_url=booking.meet_url
    )
