"""Free discovery call booked from /decouverte, and its follow-up (real PostgreSQL, fake Google/Gmail/Fireflies/Codex)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, Customer, SessionReport, Settings
from app.routers import public
from app.services import follow_up, session_reports
from app.services.rate_limit import RateLimiter
from app.services.session_reports import Gateways
from tests.conftest import ADMIN_PASSWORD, NOW, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 6, 9, 30)
END = SLOT + timedelta(minutes=30)
PROSPECT = "paul@example.com"


@pytest.fixture(autouse=True)
def fresh_limiter():
    public.discovery_limiter.reset()


def book(client, start=SLOT, **kw):
    body = {"name": "Paul Prospect", "email": PROSPECT, "start": start.isoformat(), **kw}
    return client.post("/api/discovery", json=body)


def set_settings(**values):
    with SessionLocal() as db:
        db.execute(update(Settings).values(**values))
        db.commit()


def bookings() -> list[Booking]:
    with SessionLocal() as db:
        return db.scalars(select(Booking).order_by(Booking.id)).all()


# --- page and slots ----------------------------------------------------------------------------------------------


def test_info_gives_the_call_length(client):
    assert client.get("/api/discovery").json() == {
        "consultant_name": "Suan Tay",
        "timezone": "Europe/Paris",
        "duration_min": 30,
        "nda_available": False,
    }


def test_slots_last_30_minutes_every_30_minutes_after_the_notice(client):
    slots = client.get("/api/discovery/availability").json()["slots"]
    # Monday 08:00 + 24 h notice: from Tuesday 09:00 (weekly hours 09-18).
    assert slots[:3] == [
        {"start": "2026-10-06T09:00:00+02:00", "end": "2026-10-06T09:30:00+02:00"},
        {"start": "2026-10-06T09:30:00+02:00", "end": "2026-10-06T10:00:00+02:00"},
        {"start": "2026-10-06T10:00:00+02:00", "end": "2026-10-06T10:30:00+02:00"},
    ]
    assert all(s["start"] > NOW.isoformat() for s in slots)


def test_busy_calendars_and_paid_sessions_remove_slots(client, fakes, token_for):
    fakes["calendar"].busy["cal-principal"] = [(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11))]
    token = token_for()
    assert client.post("/api/bookings", json={"token": token, "start": paris(2026, 10, 6, 14).isoformat()}).status_code == 201
    starts = {s["start"][11:16] for s in client.get("/api/discovery/availability").json()["slots"] if s["start"][:10] == "2026-10-06"}
    # 15 min buffers around 10:00-11:00 and 14:00-15:00.
    assert {"09:00", "11:30", "13:00", "15:30"} <= starts
    assert not starts & {"09:30", "10:00", "10:30", "11:00", "13:30", "14:00", "14:30", "15:00"}


def test_closed_discovery_calls(client):
    set_settings(discovery_enabled=False)
    for r in (client.get("/api/discovery"), client.get("/api/discovery/availability"), book(client)):
        assert (r.status_code, r.json()["code"]) == (404, "discovery_closed")


def test_duration_comes_from_the_settings(client):
    set_settings(discovery_duration_min=45)
    slots = client.get("/api/discovery/availability").json()["slots"]
    assert slots[1] == {"start": "2026-10-06T09:45:00+02:00", "end": "2026-10-06T10:30:00+02:00"}


# --- booking -----------------------------------------------------------------------------------------------------


def test_booking_creates_the_event_and_emails_prospect_and_admin(client, fakes):
    r = book(client, message="Automatiser mes devis", locale="en", timezone="America/Montreal")
    assert r.status_code == 201, r.text
    assert r.json() == {
        "start": "2026-10-06T09:30:00+02:00",
        "end": "2026-10-06T10:00:00+02:00",
        "meet_url": "https://meet.google.com/abc-defg-hij",
    }
    [event] = fakes["calendar"].events
    assert event["calendar_id"] == "booking-cal"
    assert event["summary"] == "Discovery call - Paul Prospect"
    assert event["attendee_email"] == PROSPECT
    assert "Free 30-minute discovery call" in event["description"]
    assert "Topic:\nAutomatiser mes devis" in event["description"]
    assert "Client time zone: America/Montreal" in event["description"]

    [b] = bookings()
    assert (b.kind, b.status, b.purchase_id, b.locale, b.customer_timezone) == (
        "discovery", "confirmed", None, "en", "America/Montreal",
    )
    prospect, admin = fakes["mailer"].sent
    assert (prospect["to"], prospect["subject"]) == (PROSPECT, "Your IAfluence discovery call is confirmed")
    assert "free 30-minute discovery call" in prospect["body"]
    assert "03:30 - 04:00 (Montreal time)" in prospect["body"]
    assert "Paris time:\nTuesday 6 October 2026, 09:30 - 10:00" in prospect["body"]
    assert (admin["to"], admin["subject"]) == ("admin@iafluence.test", "NOUVEL APPEL DÉCOUVERTE")
    assert "Paul Prospect" in admin["body"] and "Automatiser mes devis" in admin["body"]
    assert "06/10/2026\n09:30 - 10:00" in admin["body"]


def test_french_by_default_without_topic(client, fakes):
    assert book(client, locale="de").status_code == 201
    [event] = fakes["calendar"].events
    assert event["summary"] == "Appel découverte - Paul Prospect"
    assert "Sujet" not in event["description"]
    prospect, admin = fakes["mailer"].sent
    assert prospect["subject"] == "Votre appel découverte IAfluence est confirmé"
    assert "Heure de Paris" not in prospect["body"]
    assert "Sujet indiqué" not in admin["body"]


def test_one_upcoming_call_per_email(client, fakes):
    assert book(client).status_code == 201
    r = book(client, start=SLOT + timedelta(days=1), email=PROSPECT.upper())
    assert (r.status_code, r.json()["code"]) == (409, "discovery_already_booked")
    assert len(fakes["calendar"].events) == 1


def test_a_known_customer_keeps_their_name(client, token_for):
    token_for(name="Jean Dupont", email="jean@example.com")
    assert book(client, name="Usurpateur", email="jean@example.com").status_code == 201
    with SessionLocal() as db:
        assert db.scalar(select(Customer.name).where(Customer.email == "jean@example.com")) == "Jean Dupont"


@pytest.mark.parametrize("start", [paris(2026, 10, 6, 9, 15), paris(2026, 10, 5, 14), paris(2026, 10, 10, 10)])
def test_slots_not_offered_are_refused(client, start):
    r = book(client, start=start)
    assert (r.status_code, r.json()["code"]) == (422, "slot_invalid")


def test_slot_taken_meanwhile(client, fakes):
    fakes["calendar"].busy["cal-formation"] = [(SLOT, END)]
    r = book(client)
    assert (r.status_code, r.json()["code"]) == (409, "slot_taken")
    assert bookings() == []


def test_calendar_down(client, fakes):
    fakes["calendar"].errors.add("cal-principal")
    assert book(client).json()["code"] == "calendar_unavailable"
    assert client.get("/api/discovery/availability").status_code == 503


def test_honeypot_is_refused_without_booking(client, fakes):
    r = book(client, website="https://spam.example")
    assert (r.status_code, r.json()["code"]) == (400, "rejected")
    assert fakes["calendar"].events == []


def test_attempts_are_limited_per_address(client):
    for _ in range(10):
        assert book(client, start=paris(2026, 10, 6, 9, 15)).status_code == 422
    r = book(client)
    assert (r.status_code, r.json()["code"]) == (429, "too_many_attempts")
    # Another visitor (address set by Caddy) is not affected.
    r = client.post(
        "/api/discovery",
        json={"name": "Autre", "email": "autre@example.com", "start": SLOT.isoformat()},
        headers={"X-Real-IP": "203.0.113.9"},
    )
    assert r.status_code == 201


def test_rate_limiter_window():
    limiter = RateLimiter(limit=2, window=timedelta(hours=1))
    assert limiter.hit("a", NOW) and limiter.hit("a", NOW)
    assert not limiter.hit("a", NOW + timedelta(minutes=59))
    assert limiter.hit("b", NOW)
    assert limiter.hit("a", NOW + timedelta(hours=1))


@pytest.mark.parametrize(
    "body",
    [
        {"name": " ", "email": PROSPECT},
        {"name": "Paul", "email": "pas-un-email"},
        {"name": "Paul", "email": PROSPECT, "message": "x" * 1001},
    ],
)
def test_invalid_forms(client, body):
    assert client.post("/api/discovery", json=body | {"start": SLOT.isoformat()}).status_code == 422


# --- admin -------------------------------------------------------------------------------------------------------


def test_admin_sees_and_cancels_the_call(client, fakes):
    assert book(client).status_code == 201
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200
    [upcoming] = client.get("/api/admin/overview").json()["upcoming"]
    assert (upcoming["kind"], upcoming["product"], upcoming["customer"]) == ("discovery", "Appel découverte", "Paul Prospect")
    fakes["mailer"].sent.clear()
    r = client.post(f"/api/admin/bookings/{upcoming['booking_id']}/cancel", json={"notify": True})
    assert r.json() == {"status": "cancelled"}
    assert fakes["calendar"].deleted == ["evt_1"]
    assert fakes["mailer"].sent == []
    # The email can book again (the fake calendar keeps deleted events busy: another slot).
    assert book(client, start=SLOT + timedelta(hours=2)).status_code == 201


# --- end of the call ---------------------------------------------------------------------------------------------


@pytest.fixture
def reports_on(monkeypatch):
    monkeypatch.setattr(get_config(), "fireflies_api_key", "ff-key")
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")


def test_without_reports_a_thank_you_draft(client, fakes):
    assert book(client, locale="es").status_code == 201
    fakes["mailer"].sent.clear()
    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 1
    [draft] = fakes["mailer"].drafts
    assert (draft["to"], draft["subject"]) == (PROSPECT, "Gracias por nuestra llamada de descubrimiento")
    assert "del martes, 6 de octubre de 2026" in draft["body"]
    assert "https://iafluence.fr" in draft["body"]
    assert bookings()[0].status == "completed"


def test_late_close_sends_nothing(client, fakes):
    assert book(client).status_code == 201
    fakes["mailer"].sent.clear()
    assert follow_up.process_finished_sessions(fakes["mailer"], END + timedelta(days=2)) == 0
    assert fakes["mailer"].drafts == []


def test_report_of_the_call_is_drafted_with_the_summary(client, fakes, reports_on):
    assert book(client).status_code == 201
    fakes["mailer"].sent.clear()
    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 1
    fakes["fireflies"].add("ff_disc", SLOT + timedelta(minutes=1), (PROSPECT,))
    gw = Gateways(mailer=fakes["mailer"], fireflies=fakes["fireflies"], codex=fakes["codex"])
    session_reports.process(gw, END + timedelta(minutes=5))

    [turn] = fakes["codex"].turns
    assert '"type_rdv": "appel_decouverte"' in turn["prompt"]
    assert '"prestation": "Appel découverte gratuit (30 min)"' in turn["prompt"]
    assert "heures_restantes" not in turn["prompt"]
    [draft] = fakes["mailer"].drafts
    assert (draft["to"], draft["subject"]) == (PROSPECT, "Compte rendu de notre appel découverte")
    assert "Merci pour notre appel découverte du mardi 6 octobre 2026." in draft["body"]
    assert "Démarrer par les devis" in draft["body"]
    assert "https://iafluence.fr" in draft["html"]
    assert draft["images"]
    with SessionLocal() as db:
        r = db.scalar(select(SessionReport))
        assert (r.status, r.delivery, r.with_summary) == ("drafted", "draft", True)


def test_report_sent_directly_only_when_allowed(client, fakes, reports_on):
    assert book(client).status_code == 201
    with SessionLocal() as db:
        db.execute(update(Customer).values(auto_send_next_link=True))
        db.commit()
    set_settings(send_reports_without_review=True)
    follow_up.process_finished_sessions(fakes["mailer"], END)
    fakes["fireflies"].add("ff_disc", SLOT, (PROSPECT,))
    session_reports.process(Gateways(fakes["mailer"], fakes["fireflies"], fakes["codex"]), END + timedelta(minutes=5))
    assert [m["subject"] for m in fakes["mailer"].sent][-1] == "Compte rendu de notre appel découverte"
    assert fakes["mailer"].drafts == []


def test_without_transcript_the_thanks_are_drafted(client, fakes, reports_on, monkeypatch):
    assert book(client).status_code == 201
    follow_up.process_finished_sessions(fakes["mailer"], END)
    fakes["mailer"].sent.clear()
    gw = Gateways(fakes["mailer"], fakes["fireflies"], fakes["codex"])
    session_reports.process(gw, END + timedelta(hours=7))
    [draft] = fakes["mailer"].drafts
    assert draft["subject"] == "Merci pour notre appel découverte"
    assert [m["subject"] for m in fakes["mailer"].sent] == [session_reports.ALERT_SUBJECT]
