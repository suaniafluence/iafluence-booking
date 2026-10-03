"""« Autres réunions » : summarize a meeting booked outside the app, on demand (real PostgreSQL, fake Fireflies/Codex)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app import deps, main
from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, Customer, SessionReport, Settings
from app.services import session_reports
from app.services.fireflies import FirefliesError, Sentence
from app.services.session_reports import Gateways
from tests.conftest import staff_login, ADMIN_PASSWORD, NOW, paris

pytestmark = pytest.mark.usefixtures("db_clean")

# Monday 5 October 2026, 10:30 — the admin asks for the report at 12:00.
MEETING = paris(2026, 10, 5, 10, 30)
LATER = paris(2026, 10, 5, 12)
GUEST = "claire@exemple.fr"


@pytest.fixture(autouse=True)
def reports_on(monkeypatch):
    monkeypatch.setattr(get_config(), "fireflies_api_key", "ff-key")
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")
    monkeypatch.setattr(get_config(), "mail_from", "suan@iafluence.fr")


@pytest.fixture
def admin(client):
    staff_login(client)
    main.app.dependency_overrides[deps.get_now] = lambda: LATER
    return client


@pytest.fixture
def gw(fakes):
    return Gateways(mailer=fakes["mailer"], fireflies=fakes["fireflies"], codex=fakes["codex"])


def ask(admin, **kw):
    body = {
        "transcript_id": "ff_ext",
        "title": "Point projet - Exemple SAS",
        "start": MEETING.isoformat(),
        "end": (MEETING + timedelta(minutes=45)).isoformat(),
        "name": "Claire Martin",
        "email": GUEST,
        "locale": "fr",
    } | kw
    return admin.post("/api/consultant/meetings", json=body)


def report() -> SessionReport:
    with SessionLocal() as db:
        return db.scalar(select(SessionReport))


# --- listing -----------------------------------------------------------------------------------------------------


def test_recent_recordings_newest_first_without_the_admin(admin, fakes, token_for):
    token_for(name="Jean Dupont", email="jean@example.com")
    ff = fakes["fireflies"]
    ff.add("ff_old", NOW - timedelta(days=8), ("jean@example.com",))
    ff.add("ff_jean", NOW - timedelta(days=2), ("suan@iafluence.fr", "inconnu@example.com", "jean@example.com"), title="Suivi Jean")
    ff.add("ff_ext", MEETING, (GUEST, "admin@iafluence.test"), title="Point projet - Exemple SAS", duration_min=45)
    ff.add("ff_solo", MEETING - timedelta(hours=1), ("suan@iafluence.fr",))
    r = admin.get("/api/consultant/meetings")
    assert r.status_code == 200, r.text
    assert r.json()["meetings"] == [
        {
            "transcript_id": "ff_ext",
            "title": "Point projet - Exemple SAS",
            "start": "2026-10-05T10:30:00+02:00",
            "end": "2026-10-05T11:15:00+02:00",
            "participants": [GUEST],
            "suggested_email": GUEST,
            "suggested_name": None,
            "report_id": None,
        },
        {
            "transcript_id": "ff_solo",
            "title": None,
            "start": "2026-10-05T09:30:00+02:00",
            # No duration from Fireflies: 30 min.
            "end": "2026-10-05T10:00:00+02:00",
            "participants": [],
            "suggested_email": None,
            "suggested_name": None,
            "report_id": None,
        },
        {
            "transcript_id": "ff_jean",
            "title": "Suivi Jean",
            "start": "2026-10-03T08:00:00+02:00",
            "end": "2026-10-03T08:30:00+02:00",
            "participants": ["inconnu@example.com", "jean@example.com"],
            # A known customer first, with their name.
            "suggested_email": "jean@example.com",
            "suggested_name": "Jean Dupont",
            "report_id": None,
        },
    ]
    assert ff.list_calls == [(LATER - timedelta(days=7), LATER)]


def test_a_recording_already_summarized_shows_its_report(admin, fakes):
    fakes["fireflies"].add("ff_ext", MEETING, (GUEST,))
    assert ask(admin).status_code == 201
    [m] = admin.get("/api/consultant/meetings").json()["meetings"]
    assert m["report_id"] == report().id


def test_listing_needs_reports_on(admin, monkeypatch):
    monkeypatch.setattr(get_config(), "fireflies_api_key", "")
    assert admin.get("/api/consultant/meetings").status_code == 409
    assert ask(admin).status_code == 409


def test_fireflies_down(admin, fakes):
    fakes["fireflies"].fail = FirefliesError("quota de l'API Fireflies atteint")
    r = admin.get("/api/consultant/meetings")
    assert (r.status_code, r.json()["detail"]) == (502, "Fireflies ne répond pas : quota de l'API Fireflies atteint.")


def test_admin_only(client):
    assert client.get("/api/consultant/meetings").status_code == 401
    assert client.post("/api/consultant/meetings", json={}).status_code == 401


# --- report ------------------------------------------------------------------------------------------------------


def test_report_is_summarized_and_always_left_as_a_draft(admin, fakes, gw):
    fakes["fireflies"].add("ff_ext", MEETING, (GUEST,), sentences=[("Claire", "Notre projet de chatbot")])
    with SessionLocal() as db:
        db.add(Customer(name="Claire M.", email=GUEST, auto_send_next_link=True))
        db.execute(update(Settings).values(send_reports_without_review=True))
        db.commit()
    r = ask(admin, email=GUEST.upper(), locale="en")
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        booking = db.scalar(select(Booking))
        assert (booking.kind, booking.status, booking.purchase_id, booking.title, booking.locale) == (
            "meeting", "completed", None, "Point projet - Exemple SAS", "en",
        )
        assert db.scalar(select(Customer.name).where(Customer.email == GUEST)) == "Claire Martin"
    assert r.json() == {"report_id": report().id, "booking_id": booking.id}
    assert (report().status, report().fireflies_transcript_id) == ("summarizing", "ff_ext")

    session_reports.process(gw, LATER + timedelta(minutes=1))
    [turn] = fakes["codex"].turns
    assert '"type_rdv": "reunion"' in turn["prompt"] and '"titre": "Point projet - Exemple SAS"' in turn["prompt"]
    assert "Claire : Notre projet de chatbot" in turn["prompt"]
    assert "seance_numero" not in turn["prompt"]
    assert fakes["mailer"].sent == []
    [draft] = fakes["mailer"].drafts
    assert (draft["to"], draft["subject"]) == (GUEST, "Summary of our meeting on 05/10/2026")
    assert "Thank you for our meeting on Monday 5 October 2026. Here is the summary." in draft["body"]
    assert "iafluence.fr" not in draft["body"].replace("IAfluence", "")
    assert draft["images"]
    assert (report().status, report().delivery, report().with_summary) == ("drafted", "draft", True)

    [row] = admin.get("/api/consultant/overview").json()["reports"]["sessions"]
    assert (row["kind"], row["product"], row["customer"]) == ("meeting", "Point projet - Exemple SAS", "Claire Martin")


def test_untitled_meeting_is_listed_as_a_meeting(admin, fakes):
    assert ask(admin, title=None).status_code == 201
    [row] = admin.get("/api/consultant/overview").json()["reports"]["sessions"]
    assert row["product"] == "Réunion"


def test_one_report_per_recording(admin, fakes):
    assert ask(admin).status_code == 201
    r = ask(admin, email="autre@example.com")
    assert (r.status_code, r.json()["detail"]) == (409, "Cette réunion a déjà un compte rendu.")


def test_end_must_follow_start(admin):
    r = ask(admin, end=MEETING.isoformat())
    assert r.status_code == 422


@pytest.mark.parametrize("field,value", [("email", "x"), ("name", " "), ("locale", "de"), ("transcript_id", "")])
def test_invalid_requests(admin, field, value):
    assert ask(admin, **{field: value}).status_code == 422


def test_recording_still_processing_is_read_again(admin, fakes, gw):
    fakes["fireflies"].add("ff_ext", MEETING, (GUEST,), sentences=[])
    assert ask(admin).status_code == 201
    session_reports.process(gw, LATER)
    assert report().status == "waiting_transcript"
    fakes["fireflies"].transcripts["ff_ext"] = [Sentence("Claire", "Bonjour")]
    session_reports.process(gw, LATER + timedelta(minutes=5))
    session_reports.process(gw, LATER + timedelta(minutes=6))
    assert report().status == "drafted"
    assert fakes["mailer"].drafts[0]["subject"] == "Compte rendu de notre réunion du 05/10/2026"


def test_no_email_without_a_summary(admin, fakes, gw):
    fakes["fireflies"].add("ff_ext", MEETING, (GUEST,), sentences=[])
    assert ask(admin).status_code == 201
    session_reports.process(gw, LATER)
    r = admin.post(f"/api/consultant/reports/{report().id}/draft-without-summary")
    assert r.status_code == 409
    session_reports.process(gw, LATER + timedelta(hours=7))
    assert report().status == "failed"
    assert report().error == "Pas de compte rendu : aucun email préparé pour cette réunion."
    assert fakes["mailer"].drafts == []
