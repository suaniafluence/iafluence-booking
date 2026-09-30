"""Dependency wiring, Google client construction and demo fakes — pure, no database."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app import deps
from app.config import Config
from app.dev_fakes import PARIS, DemoCalendar, DemoMailer, DemoStripe
from app.services import google_client
from app.services.availability import Interval
from app.services.calendar_service import GoogleCalendarGateway
from app.services.email_service import GmailMailer
from app.services.stripe_service import LiveStripeGateway, PaymentInvalid, parse_checkout


@pytest.fixture
def fresh_deps():
    for f in (deps.get_calendar, deps.get_mailer, deps.get_stripe):
        f.cache_clear()
    yield
    for f in (deps.get_calendar, deps.get_mailer, deps.get_stripe):
        f.cache_clear()


@pytest.mark.parametrize(
    "fake, expected",
    [(True, (DemoCalendar, DemoMailer, DemoStripe)), (False, (GoogleCalendarGateway, GmailMailer, LiveStripeGateway))],
    ids=["demo", "live"],
)
def test_gateways_follow_fake_integrations_flag(monkeypatch, fresh_deps, fake, expected):
    monkeypatch.setattr(deps, "get_config", lambda: Config(fake_integrations=fake))
    got = (deps.get_calendar(), deps.get_mailer(), deps.get_stripe())
    assert tuple(type(g) for g in got) == expected
    # Singletons: the demo calendar must keep its in-memory events between requests.
    assert deps.get_calendar() is got[0]


def test_get_now_is_aware_utc():
    now = deps.get_now()
    assert now.tzinfo is UTC
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)


def test_google_credentials_come_from_config(monkeypatch):
    monkeypatch.setattr(
        google_client,
        "get_config",
        lambda: Config(google_client_id="cid", google_client_secret="csecret", google_refresh_token="rtok"),
    )
    creds = google_client.credentials()
    assert (creds.client_id, creds.client_secret, creds.refresh_token) == ("cid", "csecret", "rtok")
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert set(creds.scopes) == set(google_client.SCOPES)
    assert "https://www.googleapis.com/auth/gmail.send" in google_client.SCOPES
    # Least privilege: no scope that can read event details or emails.
    assert not any(s.endswith("/calendar") or s.endswith("calendar.readonly") or "gmail.readonly" in s for s in google_client.SCOPES)


@pytest.mark.parametrize("factory, service", [("calendar_api", ("calendar", "v3")), ("gmail_api", ("gmail", "v1"))])
def test_api_clients_are_built_once(monkeypatch, factory, service):
    built = []
    monkeypatch.setattr(google_client, "credentials", lambda: "CREDS")
    monkeypatch.setattr(google_client, "build", lambda *a, **kw: built.append((a, kw)) or object())
    fn = getattr(google_client, factory)
    fn.cache_clear()
    try:
        assert fn() is fn()
    finally:
        fn.cache_clear()
    assert built == [(service, {"credentials": "CREDS", "cache_discovery": False})]


# --- demo fakes -----------------------------------------------------------------------


def paris(y, m, d, hh):
    return datetime(y, m, d, hh, tzinfo=PARIS)


def test_demo_calendar_recurring_busy_blocks():
    # Monday 5 -> Sunday 11 October 2026.
    busy = DemoCalendar().free_busy(["x"], paris(2026, 10, 5, 0), paris(2026, 10, 11, 23))
    assert busy == [
        Interval(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11)),  # Tuesday
        Interval(paris(2026, 10, 7, 14), paris(2026, 10, 7, 16)),  # Wednesday
        Interval(paris(2026, 10, 8, 10), paris(2026, 10, 8, 11)),  # Thursday
    ]


def test_demo_calendar_created_events_become_busy(caplog):
    caplog.set_level(logging.INFO)
    cal = DemoCalendar()
    ev = cal.create_event("cal", summary="Conseil IA - Jean", start=paris(2026, 10, 5, 9), end=paris(2026, 10, 5, 10))
    assert ev.event_id.startswith("demo_") and len(ev.event_id) == len("demo_") + 8
    assert ev.meet_url.startswith("https://meet.google.com/")
    assert [len(p) for p in ev.meet_url.rsplit("/", 1)[1].split("-")] == [3, 4, 3]
    assert Interval(paris(2026, 10, 5, 9), paris(2026, 10, 5, 10)) in cal.free_busy(["x"], paris(2026, 10, 5, 0), paris(2026, 10, 5, 23))
    cal.delete_event("cal", ev.event_id)
    assert "Conseil IA - Jean" in caplog.text and ev.event_id in caplog.text


def test_demo_mailer_logs_instead_of_sending(caplog):
    caplog.set_level(logging.INFO)
    DemoMailer().send("jean@example.com", "Sujet", "Corps")
    assert "jean@example.com" in caplog.text and "Sujet" in caplog.text and "Corps" in caplog.text


def test_demo_stripe_sessions_are_valid_checkouts():
    info = parse_checkout(DemoStripe().retrieve_checkout_session("cs_demo_3h_marie"))
    assert (info.hours, info.email, info.name, info.amount_cents) == (3, "marie@example.com", "Marie Démo", 45_000)
    assert (info.product_id, info.payment_intent_id) == ("prod_demo_3h", "pi_demo_marie")


@pytest.mark.parametrize("sid", ["cs_demo_xh_marie", "cs_demo_3h_", "cs_demo_3h_Marie", "cs_live_123", "xcs_demo_3h_a"])
def test_demo_stripe_rejects_other_ids(sid):
    with pytest.raises(PaymentInvalid):
        DemoStripe().retrieve_checkout_session(sid)


def test_demo_stripe_has_no_webhooks():
    with pytest.raises(ValueError):
        DemoStripe().construct_event(b"{}", "sig")


def test_booking_errors_carry_http_status_code_and_message():
    from app.services import booking_service as bs

    assert (bs.BookingError().message, bs.BookingError().status_code) == ("Réservation impossible.", 400)
    custom = bs.SlotTaken("Autre message")
    assert (custom.message, str(custom), custom.code, custom.status_code) == ("Autre message", "Autre message", "slot_taken", 409)
    assert bs.SlotTaken().message == bs.SLOT_TAKEN_MESSAGE
    assert [(e.status_code, e.code) for e in (bs.InvalidToken, bs.NoHoursLeft, bs.SlotInvalid, bs.CalendarDown, bs.CalendarWriteFailed)] == [
        (404, "invalid_token"), (409, "no_hours_left"), (422, "slot_invalid"), (503, "calendar_unavailable"), (502, "calendar_write_failed"),
    ]


def test_booking_tokens_are_256_bit_url_safe_and_unique():
    import base64
    import re

    from app.services.tokens import new_token

    tokens = {new_token() for _ in range(200)}
    assert len(tokens) == 200
    for t in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", t)
        assert len(base64.urlsafe_b64decode(t + "=")) == 32
