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
        self.freebusy_calls: list[list[str]] = []
        self.fail_create = False
        self.create_delay = 0.0
        self._lock = threading.Lock()

    def free_busy(self, calendar_ids, time_min, time_max):
        from app.services.availability import Interval
        from app.services.calendar_service import CalendarUnavailable

        self.freebusy_calls.append(list(calendar_ids))
        if self.errors & set(calendar_ids):
            raise CalendarUnavailable("fake error")
        with self._lock:
            out = [Interval(s, e) for cid in calendar_ids for s, e in self.busy.get(cid, [])]
            # Events created through the fake are visible in free/busy like in Google.
            out += [Interval(ev["start"], ev["end"]) for ev in self.events if ev["calendar_id"] in calendar_ids]
        return out

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


class FakeMailer:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})


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

    def add_session(self, session_id, *, hours=5, paid=True, email="jean@example.com", name="Jean Dupont", pi=None):
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

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
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
                "settings, availability_rules, stripe_events RESTART IDENTITY CASCADE"
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
    return {"calendar": FakeCalendar(), "mailer": FakeMailer(), "stripe": FakeStripe()}


@pytest.fixture
def client(db_clean, fakes):
    from fastapi.testclient import TestClient

    from app import deps
    from app.main import app

    app.dependency_overrides[deps.get_calendar] = lambda: fakes["calendar"]
    app.dependency_overrides[deps.get_mailer] = lambda: fakes["mailer"]
    app.dependency_overrides[deps.get_stripe] = lambda: fakes["stripe"]
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
