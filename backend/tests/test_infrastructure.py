"""Dependency wiring, Google client construction and demo fakes — pure, no database."""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from app import deps
from app.config import Config
from app import dev_fakes
from app.dev_fakes import PARIS, DemoCalendar, DemoCodex, DemoFireflies, DemoMailer, DemoStripe
from app.services import google_client, report_content
from app.services.availability import Interval
from app.services.calendar_service import GoogleCalendarGateway
from app.services.codex import CodexNotConnected, LiveCodex
from app.services.email_service import GmailMailer
from app.services.fireflies import LiveFireflies
from app.services.stripe_service import LiveStripeGateway, PaymentInvalid, parse_checkout


GATEWAYS = (deps.get_calendar, deps.get_mailer, deps.get_stripe, deps.get_fireflies, deps.get_codex)


@pytest.fixture
def fresh_deps():
    for f in GATEWAYS:
        f.cache_clear()
    yield
    for f in GATEWAYS:
        f.cache_clear()


@pytest.mark.parametrize(
    "fake, expected",
    [
        (True, (DemoCalendar, DemoMailer, DemoStripe, DemoFireflies, DemoCodex)),
        (False, (GoogleCalendarGateway, GmailMailer, LiveStripeGateway, LiveFireflies, LiveCodex)),
    ],
    ids=["demo", "live"],
)
def test_gateways_follow_fake_integrations_flag(monkeypatch, fresh_deps, fake, expected):
    monkeypatch.setattr(deps, "get_config", lambda: Config(fake_integrations=fake))
    got = tuple(f() for f in GATEWAYS)
    assert tuple(type(g) for g in got) == expected
    # Singletons: the demo calendar keeps its events, the demo Codex its connection, between requests.
    assert all(f() is g for f, g in zip(GATEWAYS, got))


@pytest.mark.parametrize(
    "values, enabled",
    [
        ({}, False),
        ({"fireflies_api_key": "k"}, False),
        ({"codex_app_server_url": "ws://codex:4500"}, False),
        ({"fireflies_api_key": "k", "codex_app_server_url": "ws://codex:4500"}, True),
        ({"fake_integrations": True}, True),
    ],
)
def test_session_reports_need_fireflies_and_codex(values, enabled):
    assert Config(**values).session_reports_enabled is enabled


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
    assert creds.scopes is None  # an older refresh token must not fail on a newly added scope
    assert {"https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.compose"} <= set(
        google_client.SCOPES
    )
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


def test_demo_calendar_events_add_a_lunch_not_fixed_yet_on_fridays():
    from app.services.calendar_service import BusyEvent

    events = DemoCalendar().busy_events("x", paris(2026, 10, 5, 0), paris(2026, 10, 11, 23), PARIS)
    assert events == [
        BusyEvent(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11)),
        BusyEvent(paris(2026, 10, 7, 14), paris(2026, 10, 7, 16)),
        BusyEvent(paris(2026, 10, 8, 10), paris(2026, 10, 8, 11)),
        BusyEvent(paris(2026, 10, 9, 12), paris(2026, 10, 9, 14), True),
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
    DemoMailer().draft("marie@example.com", "Brouillon", "Texte")
    assert "draft to marie@example.com" in caplog.text and "Brouillon" in caplog.text


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


def test_demo_mailer_saves_emails_to_the_outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(dev_fakes, "get_config", lambda: Config(demo_outbox_dir=str(tmp_path / "out")))
    from app.services import email_service

    monkeypatch.setattr(email_service, "get_config", lambda: Config(mail_from="contact@iafluence.fr"))
    mailer = DemoMailer()
    mailer.send("a@example.com", "Sujet", "Corps")
    mailer.draft("b@example.com", "Brouillon", "Texte", html="<p>Texte</p>", images={"img": b"\x89PNG"})
    files = sorted((tmp_path / "out").iterdir())
    assert [f.name.split("-", 2)[2] for f in files] == ["0001-sent.eml", "0002-draft.eml"]
    import email as email_lib
    from email import policy

    draft = email_lib.message_from_bytes(files[1].read_bytes(), policy=policy.default)
    assert draft["To"] == "b@example.com" and draft.get_content_type() == "multipart/alternative"


def test_demo_mailer_without_outbox_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dev_fakes, "get_config", lambda: Config(demo_outbox_dir=""))
    DemoMailer().draft("a@example.com", "S", "B")
    assert list(tmp_path.iterdir()) == []


def test_demo_fireflies_transcript_is_canned():
    sentences = DemoFireflies().sentences("demo_1")
    assert len(sentences) == 4 and sentences[1].speaker == "Client"


def test_demo_codex_login_is_approved_after_a_delay(monkeypatch):
    monkeypatch.setattr(dev_fakes, "DEMO_LOGIN_DELAY_S", 0.05)
    codex = DemoCodex()
    assert codex.account() is None
    done = []
    code = codex.start_login(lambda *a: done.append(a))
    assert code.verification_url == "https://auth.openai.com/codex/device"
    import re
    import time

    assert re.fullmatch(r"[A-Z]{4}-\d{4}", code.user_code)
    deadline = time.monotonic() + 3
    while not done and time.monotonic() < deadline:
        time.sleep(0.01)
    assert done == [(code.login_id, "COMPLETED", None)]
    assert codex.account().email == "demo@iafluence.fr"
    codex.logout()
    assert codex.account() is None


def test_demo_codex_login_can_be_cancelled(monkeypatch):
    monkeypatch.setattr(dev_fakes, "DEMO_LOGIN_DELAY_S", 0.2)
    codex = DemoCodex()
    done = []
    code = codex.start_login(lambda *a: done.append(a))
    codex.cancel_login(code.login_id)
    codex.cancel_login("unknown")
    import time

    time.sleep(0.3)
    assert done == [] and codex.account() is None


@pytest.mark.parametrize("last, step", [(False, "Construire et tester"), (True, "Poursuivre en autonomie")])
def test_demo_codex_writes_a_valid_report(last, step):
    codex = DemoCodex()
    prompt = report_content.build_prompt(
        {"client": "Jean Démo", "seance_numero": 3, "derniere_seance": last}, ["Client : bonjour"]
    )
    with pytest.raises(CodexNotConnected):
        codex.run_turn(instructions="", prompt=prompt, output_schema={})
    codex.connected = True
    output = report_content.parse_output(codex.run_turn(instructions="", prompt=prompt, output_schema={}))
    assert output.synthese.prochaines_etapes[0].startswith(step)
    assert "Séance n° 3 — Jean Démo" in output.image
    assert report_content.render_png(output.image).startswith(b"\x89PNG")
