"""Language and time zone from iafluence.fr through Stripe to the emails and the calendar (real PostgreSQL)."""

import pytest

from app.db import SessionLocal
from app.models import Purchase
from tests.conftest import paris

pytestmark = pytest.mark.usefixtures("db_clean")

# Thursday 8 Oct 2026 16:00 in Paris (UTC+2) = Friday 9 Oct 01:00 in Sydney (UTC+11, summer time since 4 Oct)
# = Thursday 11:00 in Santiago (UTC-3, summer time since 6 Sep).
SLOT = paris(2026, 10, 8, 16)


def book(client, token, **prefs):
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat(), **prefs})
    assert r.status_code == 201, r.text
    return r


def purchase_prefs():
    with SessionLocal() as db:
        p = db.query(Purchase).one()
        return p.locale, p.customer_timezone


def mail(fakes, subject):
    return next(m for m in fakes["mailer"].sent if m["subject"] == subject)


@pytest.mark.parametrize(
    "extra, locale",
    [
        ({"locale": "en"}, "en"),
        ({"locale": "es-419"}, "es"),
        ({"locale": "auto", "client_reference_id": "en"}, "en"),
        ({"locale": "de"}, "fr"),
        ({}, "fr"),
    ],
)
def test_language_from_the_payment_link(client, fakes, extra, locale):
    fakes["stripe"].add_session("cs_test_1", **extra)
    r = client.get("/api/checkout/cs_test_1").json()
    assert r["locale"] == locale
    assert client.get(f"/api/booking/{r['token']}").json()["locale"] == locale
    [link] = fakes["mailer"].sent
    assert f"https://booking.iafluence.test/{locale}/reservation/{r['token']}" in link["body"].splitlines()


def test_english_booking_link_email(client, fakes):
    fakes["stripe"].add_session("cs_test_1", hours=3, name="John Smith", locale="en")
    client.get("/api/checkout/cs_test_1")
    body = mail(fakes, "Book your first AI consulting session")["body"]
    assert body.startswith("Hello John Smith,\n\nThank you for purchasing 3 hours of AI consulting.")


def test_spanish_booking_link_email_via_webhook(client, fakes):
    fakes["stripe"].add_session("cs_test_1", hours=1, name="Ana García", client_reference_id="es")
    event = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {"id": "cs_test_1"}}}
    client.post("/webhooks/stripe", json=event, headers={"stripe-signature": "valid-signature"})
    body = mail(fakes, "Reserve su primera sesión de asesoría en IA")["body"]
    assert body.startswith("Hola, Ana García:\n\nGracias por contratar 1 hora de asesoría en IA.")
    assert "/es/reservation/" in body


def test_sydney_customer_sees_their_own_date_and_paris_time(client, fakes, token_for):
    token = token_for(hours=3, locale="en")
    book(client, token, locale="en", timezone="Australia/Sydney")
    assert purchase_prefs() == ("en", "Australia/Sydney")

    body = mail(fakes, "Your AI consulting session is confirmed")["body"]
    assert (
        "Date:\nFriday 9 October 2026\n\nTime:\n01:00 - 02:00 (Sydney time)\n\n"
        "Paris time:\nThursday 8 October 2026, 16:00 - 17:00\n\n"
        "Video call link:\nhttps://meet.google.com/abc-defg-hij\n\n"
        "You purchased:\n3 hours of consulting\n\n"
        "After this first session:\n2 hours still to be scheduled."
    ) in body

    [event] = fakes["calendar"].events
    assert event["summary"] == "AI consulting - Jean Dupont"
    assert event["description"].startswith("AI consulting session.\n\nHours purchased: 3 h\n")
    assert event["description"].endswith("\n\nClient time zone: Australia/Sydney")
    # Google gets Paris time and shows every attendee the event in their own time zone.
    assert (event["start"], event["timezone"]) == (SLOT, "Europe/Paris")

    # The admin email stays in French and in Paris time.
    admin = mail(fakes, "NOUVELLE RÉSERVATION — Conseil IA")["body"]
    assert "Rendez-vous :\n08/10/2026\n16:00 - 17:00\n" in admin


def test_language_switched_on_the_booking_page_wins(client, fakes, token_for):
    token = token_for(locale="en")
    book(client, token, locale="es", timezone="America/Santiago")
    assert purchase_prefs() == ("es", "America/Santiago")
    body = mail(fakes, "Su sesión de asesoría en IA está confirmada")["body"]
    assert (
        "Fecha:\nJueves, 8 de octubre de 2026\n\nHora:\n11:00 - 12:00 (hora de Santiago)\n\n"
        "Hora de París:\nJueves, 8 de octubre de 2026, 16:00 - 17:00\n\n"
    ) in body
    assert "Quedan 4 horas por programar." in body
    assert fakes["calendar"].events[0]["summary"] == "Asesoría en IA - Jean Dupont"


def test_same_clock_as_paris_shows_a_single_time(client, fakes, token_for):
    token = token_for(locale="es")
    book(client, token, timezone="Europe/Madrid")
    assert purchase_prefs() == ("es", "Europe/Madrid")
    body = mail(fakes, "Su sesión de asesoría en IA está confirmada")["body"]
    assert "Hora:\n16:00 - 17:00\n\n" in body
    assert "París" not in body


def test_unknown_language_and_time_zone_are_ignored(client, fakes, token_for):
    token = token_for()
    book(client, token, locale="xx", timezone="Mars/Olympus")
    assert purchase_prefs() == ("fr", None)
    body = mail(fakes, "Votre rendez-vous Conseil IA est confirmé")["body"]
    assert "Horaire :\n16h00 - 17h00\n\n" in body
    assert "Fuseau" not in fakes["calendar"].events[0]["description"]


def test_preferences_are_not_saved_when_the_booking_fails(client, fakes, token_for):
    token = token_for()
    fakes["calendar"].fail_create = True
    r = client.post(
        "/api/bookings", json={"token": token, "start": SLOT.isoformat(), "locale": "en", "timezone": "Asia/Tokyo"}
    )
    assert r.status_code == 502
    assert purchase_prefs() == ("fr", None)


def test_oversized_preferences_are_rejected(client, token_for):
    token = token_for()
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat(), "timezone": "A" * 65})
    assert r.status_code == 422


def test_checkout_errors_carry_a_code_for_translation(client):
    for session_id in ("cs_unknown", "pi_123"):
        r = client.get(f"/api/checkout/{session_id}")
        assert r.status_code == 404
        assert r.json() == {"detail": "Paiement introuvable ou non finalisé.", "code": "payment_not_found"}


# --- emails after the booking ---------------------------------------------------------------------


def login(client):
    from tests.conftest import ADMIN_PASSWORD

    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200


def test_cancellation_email_in_english_on_the_customer_clock(client, fakes, token_for):
    token = token_for(hours=3, name="John Smith", locale="en")
    book(client, token, timezone="Australia/Sydney")
    login(client)
    booking_id = client.get("/api/admin/overview").json()["upcoming"][0]["booking_id"]
    fakes["mailer"].sent.clear()
    assert client.post(f"/api/admin/bookings/{booking_id}/cancel", json={}).status_code == 200
    [cancelled] = fakes["mailer"].sent
    assert cancelled["subject"] == "Your AI consulting session has been cancelled"
    assert cancelled["body"].startswith(
        "Hello John Smith,\n\nYour AI consulting session on Friday 9 October 2026 (01:00 - 02:00) has been cancelled."
    )
    assert f"https://booking.iafluence.test/en/reservation/{token}" in cancelled["body"].splitlines()


def test_next_session_link_and_last_thanks_in_spanish(client, fakes, token_for):
    from datetime import timedelta

    from app.services import follow_up

    token = token_for(hours=2, name="Ana García", locale="es")
    book(client, token)
    assert follow_up.process_finished_sessions(fakes["mailer"], SLOT + timedelta(hours=1)) == 1
    [link] = fakes["mailer"].drafts
    assert link["subject"] == "Reserve su próxima sesión de asesoría en IA"
    assert "Le queda 1 hora de asesoría." in link["body"]
    assert f"https://booking.iafluence.test/es/reservation/{token}" in link["body"].splitlines()

    nxt = paris(2026, 10, 9, 10)
    assert client.post("/api/bookings", json={"token": token, "start": nxt.isoformat()}).status_code == 201
    assert follow_up.process_finished_sessions(fakes["mailer"], nxt + timedelta(hours=1)) == 1
    thanks = fakes["mailer"].drafts[-1]
    assert thanks["subject"] == "Gracias por su acompañamiento en asesoría en IA"
    assert "Su acompañamiento (2 horas de asesoría) ha finalizado." in thanks["body"]


def test_session_report_sections_and_codex_language(client, token_for):
    from app.models import Booking
    from app.services import session_reports

    assert session_reports.summary_sections({"decisions": ["a"], "objectifs": [], "actions_client": ["b"]}, "en") == [
        ("Decisions", ["a"]),
        ("Your next actions", ["b"]),
    ]
    assert session_reports.summary_sections({"prochaines_etapes": ["c"]}, "es") == [("Próximos pasos", ["c"])]
    book(client, token_for(locale="es"))
    with SessionLocal() as db:
        context = session_reports.session_context(db, db.query(Booking).one())
    assert context["langue"] == "es"
