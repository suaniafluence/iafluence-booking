"""Test setup.

DB tests need a real PostgreSQL (exclusion constraints, advisory locks):
    TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/iafluence_test uv run pytest
Without TEST_DATABASE_URL only the pure unit tests run.
"""

import json
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from argon2 import PasswordHasher

TEST_DB = os.environ.get("TEST_DATABASE_URL")
ADMIN_PASSWORD = "test-password"

if TEST_DB:
    os.environ["DATABASE_URL"] = TEST_DB
os.environ.setdefault("PUBLIC_BASE_URL", "https://booking.iafluence.test")
os.environ["ADMIN_PASSWORD_HASH"] = PasswordHasher().hash(ADMIN_PASSWORD)
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["COOKIE_SECURE"] = "false"
os.environ["STRIPE_ALLOWED_PRODUCT_IDS"] = ""
os.environ["FOLLOW_UP_POLL_SECONDS"] = "0"  # tests drive the job explicitly

PARIS = ZoneInfo("Europe/Paris")
# Monday 5 October 2026, 08:00 Paris.
NOW = datetime(2026, 10, 5, 8, 0, tzinfo=PARIS)


def paris(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=PARIS)


# --- fakes -----------------------------------------------------------------------


class FakeCalendar:
    def __init__(self):
        self.busy: dict[str, list] = {}
        self.errors: set[str] = set()
        self.events: list[dict] = []
        self.deleted: list[str] = []
        self.deleted_from: list[str] = []
        self.freebusy_calls: list[list[str]] = []
        self.fail_create = False
        self.create_delay = 0.0
        # Google shows created events in free/busy; False simulates its propagation delay.
        self.mirror_events = True
        self._lock = threading.Lock()

    def free_busy(self, calendar_ids, time_min, time_max):
        from app.services.availability import Interval
        from app.services.calendar_service import CalendarUnavailable

        self.freebusy_calls.append(list(calendar_ids))
        if self.errors & set(calendar_ids):
            raise CalendarUnavailable("fake error")
        with self._lock:
            out = [Interval(s, e) for cid in calendar_ids for s, e in self.busy.get(cid, [])]
            if self.mirror_events:
                out += [Interval(ev["start"], ev["end"]) for ev in self.events if ev["calendar_id"] in calendar_ids]
        # Like Google: only busy periods intersecting the requested range.
        return [b for b in out if b.start < time_max and b.end > time_min]

    def create_event(self, calendar_id, **kw):
        from app.services.calendar_service import CalendarWriteError, CreatedEvent

        if self.create_delay:
            time.sleep(self.create_delay)
        if self.fail_create:
            raise CalendarWriteError("fake failure")
        with self._lock:
            event_id = f"evt_{len(self.events) + 1}"
            self.events.append({"calendar_id": calendar_id, "id": event_id, **kw})
        return CreatedEvent(event_id=event_id, meet_url="https://meet.google.com/abc-defg-hij" if kw["with_meet"] else None)

    def delete_event(self, calendar_id, event_id):
        self.deleted.append(event_id)
        self.deleted_from.append(calendar_id)


class FakeMailer:
    def __init__(self):
        self.sent: list[dict] = []
        self.drafts: list[dict] = []
        self.fail = False

    def _record(self, box, to, subject, body, parts):
        if self.fail:
            raise RuntimeError("gmail down")
        box.append({"to": to, "subject": subject, "body": body, **parts})

    def send(self, to, subject, body, **parts):
        self._record(self.sent, to, subject, body, parts)

    def draft(self, to, subject, body, **parts):
        self._record(self.drafts, to, subject, body, parts)


class FakeFireflies:
    """Recordings added by the test; `sentences` of a transcript id, [] while « processing »."""

    def __init__(self):
        self.recordings: list = []
        self.transcripts: dict[str, list] = {}
        self.list_calls: list[tuple] = []
        self.fail: Exception | None = None
        self.fail_sentences: Exception | None = None

    def add(self, transcript_id, start, emails=(), meeting_link=None, sentences=None):
        from app.services.fireflies import Sentence, TranscriptMeta

        self.recordings.append(TranscriptMeta(transcript_id, start, frozenset(emails), meeting_link))
        self.transcripts[transcript_id] = [
            Sentence(*s)
            for s in (sentences if sentences is not None else [("Suan", "Bonjour"), ("Client", "Voici mon projet")])
        ]

    def list_transcripts(self, time_min, time_max):
        self.list_calls.append((time_min, time_max))
        if self.fail:
            raise self.fail
        return [r for r in self.recordings if time_min <= r.start <= time_max]

    def sentences(self, transcript_id):
        if self.fail_sentences:
            raise self.fail_sentences
        return self.transcripts[transcript_id]


VALID_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800"><rect width="1200" height="800" fill="#eef2ff"/></svg>'
SYNTHESE = {
    "objectifs": ["Cadrer le projet d'assistant"],
    "points_abordes": ["Cas d'usage prioritaires", "Choix de l'outil"],
    "decisions": ["Démarrer par les devis"],
    "actions_client": ["Rassembler dix devis"],
    "prochaines_etapes": ["Prototype à la prochaine séance"],
}


class FakeCodex:
    """Connected by default. `answers` are returned one per turn (a str, or an exception to raise)."""

    def __init__(self):
        from app.services.codex import CodexAccount

        self.connected: CodexAccount | None = CodexAccount("suan@iafluence.fr", "plus")
        self.answers: list = []
        self.turns: list[dict] = []
        self.logins: list = []
        self.cancelled: list[str] = []
        self.logged_out = 0
        self.unavailable = False

    @staticmethod
    def answer(synthese=None, image=VALID_SVG) -> str:
        return json.dumps({"synthese": synthese or SYNTHESE, "image": image})

    def _check(self):
        from app.services.codex import CodexUnavailable

        if self.unavailable:
            raise CodexUnavailable("codex app-server injoignable (ConnectionRefusedError)")

    def account(self):
        self._check()
        return self.connected

    def start_login(self, on_done):
        from app.services.codex import DeviceCode

        self._check()
        code = DeviceCode(f"login-{len(self.logins) + 1}", "https://auth.openai.com/codex/device", "ABCD-1234")
        self.logins.append((code, on_done))
        return code

    def cancel_login(self, login_id):
        self._check()
        self.cancelled.append(login_id)

    def logout(self):
        self._check()
        self.logged_out += 1
        self.connected = None

    def run_turn(self, *, instructions, prompt, output_schema):
        from app.services.codex import CodexNotConnected

        self._check()
        self.turns.append({"instructions": instructions, "prompt": prompt, "output_schema": output_schema})
        if self.connected is None:
            raise CodexNotConnected("Codex n'est pas connecté")
        answer = self.answers.pop(0) if self.answers else self.answer()
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeStripe:
    def __init__(self):
        self.sessions: dict[str, dict] = {}

    def retrieve_checkout_session(self, session_id):
        from app.services.stripe_service import PaymentInvalid

        if session_id not in self.sessions:
            raise PaymentInvalid("unknown checkout session")
        return self.sessions[session_id]

    def construct_event(self, payload, signature):
        if signature != "valid-signature":
            raise ValueError("bad signature")
        return json.loads(payload)

    def add_session(
        self, session_id, *, hours=5, paid=True, email="jean@example.com", name="Jean Dupont", pi=None, **extra
    ):
        metadata = {"hours": str(hours)} if hours is not None else {}
        self.sessions[session_id] = {
            "id": session_id,
            "object": "checkout.session",
            "payment_status": "paid" if paid else "unpaid",
            "payment_intent": pi or f"pi_{session_id[3:]}",
            "amount_total": 100_00 * (hours or 1),
            "currency": "eur",
            "customer_details": {"email": email, "name": name},
            "line_items": {
                "data": [
                    {
                        "quantity": 1,
                        "description": f"Conseil IA - {hours}h",
                        "price": {"product": {"id": f"prod_{hours}h", "name": f"Conseil IA - {hours}h", "metadata": metadata}},
                    }
                ]
            },
            **extra,
        }
        return self.sessions[session_id]


# --- fixtures --------------------------------------------------------------------

requires_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="session")
def migrated_db():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set")
    from alembic import command
    from alembic.config import Config

    # No ini file: its [loggers] section would run fileConfig(), which disables every app logger (caplog).
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db_clean(migrated_db):
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.models import CalendarSource
    from app.services.calendar_service import freebusy_cache
    from scripts.seed_settings import seed

    with SessionLocal() as db:
        db.execute(
            text(
                "TRUNCATE customers, purchases, booking_tokens, bookings, calendar_sources, "
                "settings, availability_rules, stripe_events, session_reports, codex_logins RESTART IDENTITY CASCADE"
            )
        )
        db.commit()
    seed(admin_email="admin@iafluence.test", booking_calendar="booking-cal")
    with SessionLocal() as db:
        db.add_all(
            [
                CalendarSource(google_calendar_id="cal-principal", name="Agenda principal"),
                CalendarSource(google_calendar_id="cal-formation", name="Formation"),
                CalendarSource(google_calendar_id="cal-off", name="Désactivé", enabled=False),
            ]
        )
        db.commit()
    freebusy_cache.clear()
    yield


@pytest.fixture
def fakes():
    return {
        "calendar": FakeCalendar(),
        "mailer": FakeMailer(),
        "stripe": FakeStripe(),
        "fireflies": FakeFireflies(),
        "codex": FakeCodex(),
    }


@pytest.fixture
def client(db_clean, fakes):
    from fastapi.testclient import TestClient

    from app import deps
    from app.main import app

    app.dependency_overrides[deps.get_calendar] = lambda: fakes["calendar"]
    app.dependency_overrides[deps.get_mailer] = lambda: fakes["mailer"]
    app.dependency_overrides[deps.get_stripe] = lambda: fakes["stripe"]
    app.dependency_overrides[deps.get_fireflies] = lambda: fakes["fireflies"]
    app.dependency_overrides[deps.get_codex] = lambda: fakes["codex"]
    app.dependency_overrides[deps.get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def token_for(client, fakes):
    """Pay + exchange a checkout session, return its booking token."""

    def _make(session_id="cs_test_1", **kw):
        fakes["stripe"].add_session(session_id, **kw)
        r = client.get(f"/api/checkout/{session_id}")
        assert r.status_code == 200, r.text
        return r.json()["token"]

    return _make
