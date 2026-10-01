"""Business emails. Each function opens its own DB session so it can run as a background task."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import SessionLocal
from app.i18n import text
from app.models import Booking, BookingToken, Purchase
from app.services import formatting as fmt
from app.services.email_service import Mailer, render, send_safely
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)


def booking_url(token: str, locale: str = "fr") -> str:
    return f"{get_config().public_base_url.rstrip('/')}/{locale}/reservation/{token}"


def active_token(db: Session, purchase_id: int) -> str | None:
    """Newest non-revoked booking token of a purchase."""
    return db.scalar(
        select(BookingToken.token)
        .where(BookingToken.purchase_id == purchase_id, BookingToken.revoked_at.is_(None))
        .order_by(BookingToken.id.desc())
    )


def send_booking_cancelled(mailer: Mailer, booking_id: int) -> None:
    """Admin cancelled a session: the hour is back, send the link to pick another slot."""
    with SessionLocal() as db:
        booking = db.get(Booking, booking_id)
        token = active_token(db, booking.purchase_id)
        if token is None:
            log.info("booking %s cancelled: no active link, client not emailed", booking_id)
            return
        settings = get_settings(db)
        purchase = booking.purchase
        locale = purchase.locale
        when = _when(booking, purchase.customer_timezone or settings.timezone, locale)
        if locale != "en":  # mid-sentence: "du jeudi 8 octobre", "del jueves, 8 de octubre"
            when["date_long"] = when["date_long"].lower()
        body = render(
            f"{locale}/booking_cancelled.txt",
            name=booking.customer.name,
            **when,
            booking_url=booking_url(token, locale),
            consultant_name=settings.consultant_name,
        )
        send_safely(mailer, booking.customer.email, text(locale, "subject_cancelled"), body)


def send_booking_link(mailer: Mailer, purchase_id: int, token: str) -> None:
    with SessionLocal() as db:
        purchase = db.get(Purchase, purchase_id)
        settings = get_settings(db)
        locale = purchase.locale
        body = render(
            f"{locale}/booking_link.txt",
            name=purchase.customer.name,
            product_name=purchase.product_name,
            hours_purchased_label=fmt.hours(purchase.hours_purchased, locale),
            booking_url=booking_url(token, locale),
            consultant_name=settings.consultant_name,
        )
        send_safely(mailer, purchase.customer.email, text(locale, "subject_booking_link"), body)


def _when(booking: Booking, tz: str, locale: str) -> dict[str, str]:
    sep = "h" if locale == "fr" else ":"
    return {
        "date_long": fmt.long_date(booking.start_datetime, tz, locale),
        "hour_range": fmt.hour_range(booking.start_datetime, booking.end_datetime, tz, sep),
    }


def send_next_session_link(mailer: Mailer, purchase_id: int, token: str) -> None:
    with SessionLocal() as db:
        purchase = db.get(Purchase, purchase_id)
        settings = get_settings(db)
        locale = purchase.locale
        body = render(
            f"{locale}/next_session_link.txt",
            name=purchase.customer.name,
            hours_remaining=purchase.hours_remaining,
            hours_remaining_label=fmt.hours(purchase.hours_remaining, locale),
            booking_url=booking_url(token, locale),
            consultant_name=settings.consultant_name,
        )
        customer = purchase.customer
        send_safely(
            mailer,
            customer.email,
            text(locale, "subject_next_link"),
            body,
            as_draft=not customer.auto_send_next_link,
        )


def send_last_session_thanks(mailer: Mailer, purchase_id: int) -> None:
    """Last hour used: thank the client and point to where more hours can be bought."""
    with SessionLocal() as db:
        purchase = db.get(Purchase, purchase_id)
        customer = purchase.customer
        settings = get_settings(db)
        locale = purchase.locale
        body = render(
            f"{locale}/last_session_thanks.txt",
            name=customer.name,
            hours_purchased_label=fmt.hours(purchase.hours_purchased, locale),
            shop_url=get_config().shop_url,
            consultant_name=settings.consultant_name,
        )
        send_safely(
            mailer,
            customer.email,
            text(locale, "subject_last_thanks"),
            body,
            as_draft=not customer.auto_send_next_link,
        )


def send_booking_confirmations(mailer: Mailer, booking_id: int) -> None:
    with SessionLocal() as db:
        booking = db.get(Booking, booking_id)
        purchase, customer = booking.purchase, booking.customer
        settings = get_settings(db)
        tz, locale = settings.timezone, purchase.locale

        # The customer's own clock first; Paris time is added only when it reads differently.
        paris = _when(booking, tz, locale)
        local_tz = purchase.customer_timezone or tz
        local = _when(booking, local_tz, locale)
        customer_body = render(
            f"{locale}/customer_confirmation.txt",
            first_session=purchase.hours_booked == 1,
            **local,
            local_city=fmt.tz_city(local_tz),
            paris=paris if local != paris else None,
            meet_url=booking.meet_url,
            hours_purchased_label=fmt.hours(purchase.hours_purchased, locale),
            hours_remaining=purchase.hours_remaining,
            hours_remaining_label=fmt.hours(purchase.hours_remaining, locale),
            consultant_name=settings.consultant_name,
        )
        send_safely(mailer, customer.email, text(locale, "subject_confirmation"), customer_body)

        admin_body = render(
            "admin_new_booking.txt",
            name=customer.name,
            email=customer.email,
            product_name=purchase.product_name,
            stripe_payment_id=purchase.stripe_payment_id or purchase.stripe_checkout_session_id,
            date_short=fmt.short_date(booking.start_datetime, tz),
            hour_range=fmt.hour_range(booking.start_datetime, booking.end_datetime, tz, ":"),
            meet_url=booking.meet_url,
            hours_purchased=purchase.hours_purchased,
            hours_remaining=purchase.hours_remaining,
        )
        send_safely(mailer, settings.admin_email, "NOUVELLE RÉSERVATION — Conseil IA", admin_body)


def send_refund_alert(mailer: Mailer, purchase_id: int, full_refund: bool) -> None:
    with SessionLocal() as db:
        purchase = db.get(Purchase, purchase_id)
        settings = get_settings(db)
        booking = next((b for b in purchase.bookings if b.status == "confirmed"), None)
        booking_label = (
            f"{fmt.short_date(booking.start_datetime, settings.timezone)} "
            f"{fmt.hour_range(booking.start_datetime, booking.end_datetime, settings.timezone, ':')}"
            if booking
            else None
        )
        body = render(
            "admin_refund.txt",
            name=purchase.customer.name,
            email=purchase.customer.email,
            product_name=purchase.product_name,
            stripe_payment_id=purchase.stripe_payment_id,
            booking=booking_label,
        )
        if not full_refund:
            body = "REMBOURSEMENT PARTIEL — l'accès à la réservation est conservé.\n\n" + body.replace(
                "Le lien de réservation a été révoqué.\n", ""
            )
        send_safely(mailer, settings.admin_email, "REMBOURSEMENT — Conseil IA", body)
