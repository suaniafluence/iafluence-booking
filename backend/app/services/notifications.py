"""Business emails. Each function opens its own DB session so it can run as a background task."""

import logging

from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, Purchase
from app.services import formatting as fmt
from app.services.email_service import Mailer, render, send_safely
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)


def booking_url(token: str) -> str:
    return f"{get_config().public_base_url.rstrip('/')}/reservation/{token}"


def send_booking_link(mailer: Mailer, purchase_id: int, token: str) -> None:
    with SessionLocal() as db:
        purchase = db.get(Purchase, purchase_id)
        settings = get_settings(db)
        body = render(
            "booking_link.txt",
            name=purchase.customer.name,
            product_name=purchase.product_name,
            booking_url=booking_url(token),
            consultant_name=settings.consultant_name,
        )
        send_safely(mailer, purchase.customer.email, "Réservez votre première session de conseil IA", body)


def send_booking_confirmations(mailer: Mailer, booking_id: int) -> None:
    with SessionLocal() as db:
        booking = db.get(Booking, booking_id)
        purchase, customer = booking.purchase, booking.customer
        settings = get_settings(db)
        tz = settings.timezone

        customer_body = render(
            "customer_confirmation.txt",
            date_long=fmt.long_date(booking.start_datetime, tz),
            hour_range=fmt.hour_range(booking.start_datetime, booking.end_datetime, tz, "h"),
            meet_url=booking.meet_url,
            hours_purchased_label=fmt.hours(purchase.hours_purchased),
            hours_remaining=purchase.hours_remaining,
            hours_remaining_label=fmt.hours(purchase.hours_remaining),
            consultant_name=settings.consultant_name,
        )
        send_safely(mailer, customer.email, "Votre rendez-vous Conseil IA est confirmé", customer_body)

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
