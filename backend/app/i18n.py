"""Customer-facing languages. The admin side stays in French."""

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCALES = ("fr", "en", "es")
DEFAULT_LOCALE = "fr"


def normalize_locale(raw: Any) -> str | None:
    """'en', 'en-GB', 'es-419', 'FR' -> supported code; anything else (None, 'auto', 'de') -> None."""
    if not isinstance(raw, str):
        return None
    code = raw.strip().lower()[:2]
    return code if code in LOCALES else None


def checkout_locale(session: dict[str, Any]) -> str:
    """Language chosen on iafluence.fr, carried through Stripe.

    The payment link is opened with `?locale=en` (Checkout language, stored on the session) and/or
    `?client_reference_id=en` (always stored, even when Stripe falls back to the browser language).
    """
    candidates = (session.get("locale"), session.get("client_reference_id"), (session.get("metadata") or {}).get("lang"))
    for raw in candidates:
        if locale := normalize_locale(raw):
            return locale
    return DEFAULT_LOCALE


def valid_timezone(raw: str | None) -> str | None:
    """IANA name sent by the visitor's browser (e.g. 'Australia/Sydney'), or None if unusable."""
    if not raw or len(raw) > 64:
        return None
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return raw


# Customer emails and the Google Calendar event (visible to the customer and the consultant).
TEXTS: dict[str, dict[str, str]] = {
    "fr": {
        "subject_booking_link": "Réservez votre première session de conseil IA",
        "subject_confirmation": "Votre rendez-vous Conseil IA est confirmé",
        "subject_cancelled": "Votre session de conseil IA a été annulée",
        "subject_next_link": "Réservez votre prochaine session de conseil IA",
        "subject_last_thanks": "Merci pour votre accompagnement Conseil IA",
        "subject_report_next": "Compte rendu de votre session et réservation de la suivante",
        "subject_report_last": "Compte rendu de votre dernière session de conseil IA",
        "event_summary": "Conseil IA - {name}",
        "event_description": (
            "Session de conseil IA.\n\n"
            "Heures achetées : {hours_purchased} h\n"
            "Session réservée : 1 h\n"
            "Heures restantes : {hours_remaining} h\n\n"
            "Paiement Stripe :\n{payment}"
        ),
        "event_timezone": "Fuseau horaire du client : {tz}",
        "subject_discovery_confirmation": "Votre appel découverte IAfluence est confirmé",
        "subject_discovery_report": "Compte rendu de notre appel découverte",
        "subject_discovery_thanks": "Merci pour notre appel découverte",
        "subject_meeting_report": "Compte rendu de notre réunion du {date}",
        "discovery_event_summary": "Appel découverte - {name}",
        "discovery_event_description": "Appel découverte gratuit de {minutes} min, réservé sur le site IAfluence.",
        "discovery_event_message": "Sujet indiqué :\n{message}",
        "subject_nda": "Accord de confidentialité (NDA) — IAfluence",
    },
    "en": {
        "subject_booking_link": "Book your first AI consulting session",
        "subject_confirmation": "Your AI consulting session is confirmed",
        "subject_cancelled": "Your AI consulting session has been cancelled",
        "subject_next_link": "Book your next AI consulting session",
        "subject_last_thanks": "Thank you for your AI consulting programme",
        "subject_report_next": "Your session summary and booking your next one",
        "subject_report_last": "Summary of your final AI consulting session",
        "event_summary": "AI consulting - {name}",
        "event_description": (
            "AI consulting session.\n\n"
            "Hours purchased: {hours_purchased} h\n"
            "Session booked: 1 h\n"
            "Hours remaining: {hours_remaining} h\n\n"
            "Stripe payment:\n{payment}"
        ),
        "event_timezone": "Client time zone: {tz}",
        "subject_discovery_confirmation": "Your IAfluence discovery call is confirmed",
        "subject_discovery_report": "Summary of our discovery call",
        "subject_discovery_thanks": "Thank you for our discovery call",
        "subject_meeting_report": "Summary of our meeting on {date}",
        "discovery_event_summary": "Discovery call - {name}",
        "discovery_event_description": "Free {minutes}-minute discovery call, booked on the IAfluence website.",
        "discovery_event_message": "Topic:\n{message}",
        "subject_nda": "Non-disclosure agreement (NDA) — IAfluence",
    },
    "es": {
        "subject_booking_link": "Reserve su primera sesión de asesoría en IA",
        "subject_confirmation": "Su sesión de asesoría en IA está confirmada",
        "subject_cancelled": "Su sesión de asesoría en IA ha sido cancelada",
        "subject_next_link": "Reserve su próxima sesión de asesoría en IA",
        "subject_last_thanks": "Gracias por su acompañamiento en asesoría en IA",
        "subject_report_next": "Resumen de su sesión y reserva de la siguiente",
        "subject_report_last": "Resumen de su última sesión de asesoría en IA",
        "event_summary": "Asesoría en IA - {name}",
        "event_description": (
            "Sesión de asesoría en IA.\n\n"
            "Horas contratadas: {hours_purchased} h\n"
            "Sesión reservada: 1 h\n"
            "Horas restantes: {hours_remaining} h\n\n"
            "Pago Stripe:\n{payment}"
        ),
        "event_timezone": "Zona horaria del cliente: {tz}",
        "subject_discovery_confirmation": "Su llamada de descubrimiento con IAfluence está confirmada",
        "subject_discovery_report": "Resumen de nuestra llamada de descubrimiento",
        "subject_discovery_thanks": "Gracias por nuestra llamada de descubrimiento",
        "subject_meeting_report": "Resumen de nuestra reunión del {date}",
        "discovery_event_summary": "Llamada de descubrimiento - {name}",
        "discovery_event_description": "Llamada de descubrimiento gratuita de {minutes} min, reservada en el sitio web de IAfluence.",
        "discovery_event_message": "Tema indicado:\n{message}",
        "subject_nda": "Acuerdo de confidencialidad (NDA) — IAfluence",
    },
}


def text(locale: str, key: str, **kw) -> str:
    return TEXTS.get(locale, TEXTS[DEFAULT_LOCALE])[key].format(**kw)
