"""Webhooks, admin area, notifications, settings and CLI scripts (real PostgreSQL)."""

import json
import runpy
import sys
import threading
from datetime import UTC, datetime

import pytest
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import func, select, text, update

from app.config import Config
from app.db import SessionLocal
from app.models import AvailabilityRule, Booking, BookingToken, CalendarSource, Customer, Purchase, Settings, StripeEvent
from app.routers import admin as admin_router
from app.services import settings_service, stripe_service
from tests.conftest import ADMIN_PASSWORD, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)


def webhook(client, event: dict, signature="valid-signature"):
    return client.post("/webhooks/stripe", content=json.dumps(event), headers={"stripe-signature": signature})


def stored_event(event_id):
    with SessionLocal() as db:
        return db.get(StripeEvent, event_id)


def count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


# --- webhooks -----------------------------------------------------------------------------


def test_async_payment_succeeded_fulfills_and_emails_link(client, fakes):
    fakes["stripe"].add_session("cs_test_async")
    event = {"id": "evt_async", "type": "checkout.session.async_payment_succeeded", "data": {"object": {"id": "cs_test_async"}}}
    assert webhook(client, event).json() == {"status": "ok"}
    assert count(Purchase) == 1
    [mail] = fakes["mailer"].sent
    assert mail["subject"] == "Réservez votre première session de conseil IA"
    assert "Bonjour Jean Dupont," in mail["body"]
    token = client.get("/api/checkout/cs_test_async").json()["token"]
    assert f"https://booking.iafluence.test/reservation/{token}" in mail["body"].splitlines()
    assert stored_event("evt_async").note is None


def test_checkout_webhook_for_pending_payment_is_recorded_as_ignored(client, fakes):
    fakes["stripe"].add_session("cs_test_pending", paid=False)
    event = {"id": "evt_p", "type": "checkout.session.completed", "data": {"object": {"id": "cs_test_pending"}}}
    assert webhook(client, event).json() == {"status": "ok"}
    assert count(Purchase) == 0 and fakes["mailer"].sent == []
    ev = stored_event("evt_p")
    assert (ev.type, ev.note) == ("checkout.session.completed", "ignored: payment not completed")


def test_refund_for_unknown_payment(client, fakes):
    event = {"id": "evt_r", "type": "charge.refunded", "data": {"object": {"id": "ch_1", "payment_intent": "pi_unknown", "refunded": True}}}
    assert webhook(client, event).json() == {"status": "ok"}
    assert stored_event("evt_r").note == "no matching purchase"
    assert fakes["mailer"].sent == []


def test_refund_without_payment_intent(client):
    event = {"id": "evt_r2", "type": "charge.refunded", "data": {"object": {"id": "ch_1", "refunded": True}}}
    webhook(client, event)
    assert stored_event("evt_r2").note == "no matching purchase"


def test_refund_with_expanded_payment_intent(client, fakes, token_for):
    token = token_for("cs_test_1")
    event = {"id": "evt_r3", "type": "charge.refunded",
             "data": {"object": {"id": "ch_1", "payment_intent": {"id": "pi_test_1"}, "refunded": True}}}
    webhook(client, event)
    assert client.get(f"/api/booking/{token}").status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(Purchase.payment_status)) == "refunded"
        assert db.scalar(select(BookingToken.revoked_at)) is not None


def test_full_refund_without_booking_alert(client, fakes, token_for):
    token_for("cs_test_1")
    event = {"id": "evt_r4", "type": "charge.refunded", "data": {"object": {"payment_intent": "pi_test_1", "refunded": True}}}
    webhook(client, event)
    alert = next(m for m in fakes["mailer"].sent if m["subject"] == "REMBOURSEMENT — Conseil IA")
    assert alert["to"] == "admin@iafluence.test"
    assert "Le lien de réservation a été révoqué." in alert["body"]
    assert "ATTENTION" not in alert["body"] and "PARTIEL" not in alert["body"]
    assert "Jean Dupont <jean@example.com>" in alert["body"]


def test_partial_refund_alert_does_not_claim_revocation(client, fakes, token_for):
    token_for("cs_test_1")
    event = {"id": "evt_r5", "type": "charge.refunded", "data": {"object": {"payment_intent": "pi_test_1", "refunded": False}}}
    webhook(client, event)
    alert = next(m for m in fakes["mailer"].sent if m["subject"] == "REMBOURSEMENT — Conseil IA")
    assert alert["body"].startswith("REMBOURSEMENT PARTIEL — l'accès à la réservation est conservé.\n\n")
    assert "révoqué" not in alert["body"]


def test_other_event_types_are_logged_only(client):
    assert webhook(client, {"id": "evt_o", "type": "invoice.paid", "data": {"object": {"id": "in_1"}}}).json() == {"status": "ok"}
    assert stored_event("evt_o").note == "logged only"
    assert webhook(client, {"id": "evt_o", "type": "invoice.paid", "data": {"object": {"id": "in_1"}}}).json() == {"status": "duplicate"}
    assert count(StripeEvent) == 1


def test_webhook_rejects_missing_signature(client):
    r = client.post("/webhooks/stripe", content=b"{}")
    assert r.status_code == 400 and r.json() == {"detail": "invalid signature"}
    assert count(StripeEvent) == 0


def test_processing_failure_is_not_recorded_so_stripe_retries(client, fakes, monkeypatch):
    def boom(*a):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(stripe_service, "fulfill_checkout", boom)
    with pytest.raises(RuntimeError):
        webhook(client, {"id": "evt_f", "type": "checkout.session.completed", "data": {"object": {"id": "cs_x"}}})
    assert count(StripeEvent) == 0


# --- fulfilment -----------------------------------------------------------------------------


def test_same_customer_buying_twice_is_one_customer_with_updated_name(client, fakes, token_for):
    token_for("cs_test_1", email="jean@example.com", name="Jean")
    token_for("cs_test_2", email="JEAN@example.com", name="Jean Dupont")
    with SessionLocal() as db:
        assert db.scalars(select(Customer.name)).all() == ["Jean Dupont"]
        assert db.scalar(select(func.count(Purchase.id))) == 2


def test_purchase_row_content(client, token_for):
    token_for("cs_test_1", hours=3)
    p = next(iter(_purchases()))
    assert (p.stripe_payment_id, p.product_id, p.product_name) == ("pi_test_1", "prod_3h", "Conseil IA - 3h")
    assert (p.amount_cents, p.currency, p.hours_purchased, p.hours_booked, p.payment_status) == (30_000, "eur", 3, 0, "paid")


def _purchases():
    with SessionLocal() as db:
        return db.scalars(select(Purchase)).all()


def test_concurrent_fulfilment_loser_returns_winner_token(client, fakes):
    """Webhook and redirect race: the slower insert hits ON CONFLICT and reuses the winner's token."""
    fakes["stripe"].add_session("cs_test_race")
    winner = {}

    class RacingStripe:
        def retrieve_checkout_session(self, session_id):
            if not winner:
                with SessionLocal() as other:
                    winner["result"] = stripe_service.fulfill_checkout(other, fakes["stripe"], session_id)
            return fakes["stripe"].retrieve_checkout_session(session_id)

    with SessionLocal() as db:
        loser = stripe_service.fulfill_checkout(db, RacingStripe(), "cs_test_race")
    assert winner["result"].created is True
    assert loser.created is False
    assert loser.token == winner["result"].token
    assert count(Purchase) == 1 and count(BookingToken) == 1


def test_revoked_purchase_cannot_be_refulfilled(client, fakes, token_for):
    token_for("cs_test_1")
    with SessionLocal() as db:
        db.execute(update(BookingToken).values(revoked_at=datetime.now(UTC)))
        db.commit()
        with pytest.raises(stripe_service.PaymentInvalid, match="^booking access revoked$"):
            stripe_service.fulfill_checkout(db, fakes["stripe"], "cs_test_1")


# --- admin ----------------------------------------------------------------------------------


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(admin_router.time, "sleep", slept.append)
    return slept


def login(client):
    r = client.post("/api/admin/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200
    return r


def test_login_sets_hardened_cookie(client):
    cookie = login(client).headers["set-cookie"]
    assert cookie.startswith("iaf_admin=")
    for attr in ("HttpOnly", "Max-Age=43200", "Path=/api/admin", "SameSite=strict"):
        assert attr in cookie
    assert "Secure" not in cookie  # COOKIE_SECURE=false in tests


def test_wrong_password_is_slowed_down(client, no_sleep):
    r = client.post("/api/admin/login", json={"password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Mot de passe incorrect."
    assert no_sleep == [1]
    assert "set-cookie" not in r.headers


@pytest.mark.parametrize("hash_", ["", "not-an-argon2-hash"], ids=["unset", "corrupt"])
def test_login_refused_when_hash_unusable(client, no_sleep, monkeypatch, hash_):
    monkeypatch.setattr(admin_router, "get_config", lambda: Config(admin_password_hash=hash_, session_secret="test-secret"))
    assert client.post("/api/admin/login", json={"password": ""}).status_code == 401
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 401


def test_forged_cookie_rejected(client):
    forged = URLSafeTimedSerializer("attacker-secret", salt="admin-session").dumps({"admin": True})
    client.cookies.set("iaf_admin", forged, path="/api/admin")
    r = client.get("/api/admin/overview")
    assert r.status_code == 401 and r.json()["detail"] == "Session expirée."


def test_expired_session_rejected(client, monkeypatch):
    login(client)
    assert client.get("/api/admin/overview").status_code == 200
    monkeypatch.setattr(admin_router, "SESSION_MAX_AGE", -1)
    assert client.get("/api/admin/overview").json()["detail"] == "Session expirée."


def test_logout_clears_session(client):
    login(client)
    r = client.post("/api/admin/logout")
    assert r.json() == {"status": "ok"}
    assert 'iaf_admin=""' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    assert client.get("/api/admin/overview").status_code == 401


def test_admin_overview_kpis_and_lists(client, fakes, token_for):
    t_jean = token_for("cs_test_j", hours=5, email="jean@example.com", name="Jean Dupont")
    token_for("cs_test_m", hours=2, email="marie@example.com", name="Marie Martin")
    token_for("cs_test_r", hours=3, email="rembourse@example.com", name="Remboursé")
    token_for("cs_test_p", hours=1, email="passe@example.com", name="Passé")
    assert client.post("/api/bookings", json={"token": t_jean, "start": SLOT.isoformat()}).status_code == 201
    with SessionLocal() as db:
        by_session = {p.stripe_checkout_session_id: p for p in db.scalars(select(Purchase))}
        # Control created_at: NOW is 5 Oct 2026 -> "this month" starts 1 Oct (Paris).
        db.execute(update(Purchase).values(created_at=datetime(2026, 10, 2, 10, tzinfo=UTC)))
        db.execute(update(Purchase).where(Purchase.stripe_checkout_session_id == "cs_test_m")
                   .values(created_at=datetime(2026, 9, 30, 21, 59, tzinfo=UTC)))  # 23:59 Paris, September
        db.execute(update(Purchase).where(Purchase.stripe_checkout_session_id == "cs_test_p")
                   .values(created_at=datetime(2026, 9, 30, 22, 0, tzinfo=UTC), hours_booked=1))  # 00:00 Paris, October
        db.execute(update(Purchase).where(Purchase.stripe_checkout_session_id == "cs_test_r").values(payment_status="refunded"))
        # A session already delivered (90 minutes, before NOW).
        passe = by_session["cs_test_p"]
        db.add(Booking(purchase_id=passe.id, customer_id=passe.customer_id, start_datetime=paris(2026, 10, 2, 10),
                       end_datetime=paris(2026, 10, 2, 11, 30), status="confirmed"))
        db.commit()

    login(client)
    data = client.get("/api/admin/overview").json()
    assert data["kpis"] == {
        "payments_this_month": 2,  # Jean + Passé (Marie is September, the refund is excluded)
        "revenue_this_month_cents": 60_000,
        "hours_sold": 8,
        "hours_booked": 2,
        "hours_done": 1.5,
        "hours_to_schedule": 6,
        "hours_to_deliver": 6.5,
    }
    assert data["upcoming"] == [
        {"customer": "Jean Dupont", "email": "jean@example.com", "product": "Conseil IA - 5h",
         "start": "2026-10-08T14:00:00+02:00", "end": "2026-10-08T15:00:00+02:00", "meet_url": "https://meet.google.com/abc-defg-hij"}
    ]
    clients = {c["name"]: c for c in data["clients"]}
    assert clients["Remboursé"]["payment_status"] == "refunded"
    assert clients["Marie Martin"]["created_at"] == "2026-09-30T23:59:00+02:00"
    assert clients["Passé"]["booking"]["start"] == "2026-10-02T10:00:00+02:00"
    assert data["clients"][-1]["name"] == "Marie Martin"  # newest first


def test_admin_overview_empty(client):
    login(client)
    data = client.get("/api/admin/overview").json()
    assert data["kpis"]["hours_sold"] == 0 and data["kpis"]["hours_done"] == 0
    assert data["upcoming"] == [] and data["clients"] == []


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


# --- settings --------------------------------------------------------------------------------


def test_missing_settings_row_is_explicit():
    with SessionLocal() as db:
        db.execute(text("TRUNCATE settings"))
        db.commit()
        with pytest.raises(RuntimeError, match="seed_settings"):
            settings_service.get_settings(db)


def test_booking_calendar_listed_once_and_disabled_sources_ignored():
    with SessionLocal() as db:
        db.add(CalendarSource(google_calendar_id="booking-cal", name="Rendez-vous"))
        db.commit()
        assert sorted(settings_service.busy_calendar_ids(db)) == ["booking-cal", "cal-formation", "cal-principal"]
        db.execute(update(Settings).values(booking_calendar_id=""))
        db.commit()
        db.expire_all()
        assert "" not in settings_service.busy_calendar_ids(db)


def test_slot_rules_from_database():
    with SessionLocal() as db:
        db.execute(update(Settings).values(booking_duration_min=45, slot_step_min=30, minimum_notice_min=120,
                                           maximum_window_days=7, buffer_before_min=5, buffer_after_min=10))
        db.commit()
        rules = settings_service.slot_rules(db)
    assert (rules.duration.seconds, rules.step.seconds, rules.min_notice.seconds) == (2700, 1800, 7200)
    assert (rules.max_window.days, rules.buffer_before.seconds, rules.buffer_after.seconds) == (7, 300, 600)
    assert str(rules.tz) == "Europe/Paris"
    assert sorted(rules.weekly) == [0, 1, 2, 3, 4]
    assert rules.weekly[4][0][1].hour == 17


# --- scripts -----------------------------------------------------------------------------------


def test_seed_is_idempotent_and_only_updates_given_options():
    from scripts.seed_settings import seed

    seed()
    seed(admin_email="new@iafluence.test")
    with SessionLocal() as db:
        s = db.scalar(select(Settings))
        assert (s.admin_email, s.booking_calendar_id) == ("new@iafluence.test", "booking-cal")
        assert db.scalar(select(func.count(Settings.id))) == 1
        assert db.scalar(select(func.count(AvailabilityRule.id))) == 5


def test_seed_from_scratch_via_cli(monkeypatch, capsys):
    with SessionLocal() as db:
        db.execute(text("TRUNCATE settings, availability_rules"))
        db.commit()
    monkeypatch.setattr(sys, "argv", ["seed_settings", "--admin-email", "a@b.fr", "--booking-calendar", "cal-x"])
    runpy.run_module("scripts.seed_settings", run_name="__main__")
    out = capsys.readouterr().out
    assert "settings created" in out and "default weekly hours created" in out
    with SessionLocal() as db:
        s = db.scalar(select(Settings))
        assert (s.admin_email, s.booking_calendar_id, s.timezone, s.meet_enabled) == ("a@b.fr", "cal-x", "Europe/Paris", True)
        assert (s.buffer_before_min, s.buffer_after_min, s.minimum_notice_min, s.maximum_window_days) == (15, 15, 1440, 30)


class _CalendarListApi:
    def __init__(self, pages):
        self.pages, self.tokens = pages, []

    def calendarList(self):
        return self

    def list(self, pageToken=None):
        self.tokens.append(pageToken)
        page = self.pages[len(self.tokens) - 1]
        return type("C", (), {"execute": lambda _self: page})()


def test_list_calendars_follows_pagination(monkeypatch, capsys):
    from app.services import google_client

    api = _CalendarListApi([
        {"items": [{"id": "a@group", "summary": "Formation", "accessRole": "freeBusyReader"}], "nextPageToken": "p2"},
        {"items": [{"id": "b@group", "summary": "x" * 50}]},
    ])
    monkeypatch.setattr(google_client, "calendar_api", lambda: api)
    monkeypatch.setattr(sys, "argv", ["list_calendars"])
    runpy.run_module("scripts.list_calendars", run_name="__main__")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["ACCESS", "NAME", "ID"]
    assert lines[1].split() == ["freeBusyReader", "Formation", "a@group"]
    assert lines[2].split() == ["x" * 35, "b@group"]
    assert api.tokens == [None, "p2"]


def test_list_calendars_add_source_upserts_and_reenables(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["list_calendars", "--add", "cal-off", "Personnel"])
    runpy.run_module("scripts.list_calendars", run_name="__main__")
    assert "calendar source 'Personnel' enabled" in capsys.readouterr().out
    with SessionLocal() as db:
        src = db.scalar(select(CalendarSource).where(CalendarSource.google_calendar_id == "cal-off"))
        assert (src.name, src.enabled) == ("Personnel", True)
        assert db.scalar(select(func.count(CalendarSource.id))) == 3


def test_google_oauth_init_prints_env_values(monkeypatch, capsys, tmp_path):
    import google_auth_oauthlib.flow

    secrets = tmp_path / "client_secret.json"
    secrets.write_text(json.dumps({"installed": {"client_id": "cid.apps", "client_secret": "csec"}}), encoding="utf-8")
    seen = {}

    class Flow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            seen["path"], seen["scopes"] = path, scopes
            return cls()

        def run_local_server(self, **kw):
            seen["kw"] = kw
            return type("Creds", (), {"refresh_token": "1//refresh"})()

    monkeypatch.setattr(google_auth_oauthlib.flow, "InstalledAppFlow", Flow)
    monkeypatch.setattr(sys, "argv", ["google_oauth_init", str(secrets)])
    runpy.run_module("scripts.google_oauth_init", run_name="__main__")
    out = capsys.readouterr().out
    assert "GOOGLE_CLIENT_ID=cid.apps\nGOOGLE_CLIENT_SECRET=csec\nGOOGLE_REFRESH_TOKEN=1//refresh" in out
    assert seen["kw"] == {"port": 0, "access_type": "offline", "prompt": "consent"}  # offline -> refresh token
    from app.services.google_client import SCOPES

    assert (seen["path"], seen["scopes"]) == (str(secrets), SCOPES)


def test_google_oauth_init_usage(monkeypatch):
    from scripts import google_oauth_init

    monkeypatch.setattr(sys, "argv", ["google_oauth_init"])
    with pytest.raises(SystemExit) as exc:
        google_oauth_init.main()
    assert "Usage" in str(exc.value.code)


def test_concurrent_webhook_and_redirect_via_http(client, fakes):
    """End-to-end idempotence through both entry points at once."""
    fakes["stripe"].add_session("cs_test_both")
    results = []
    barrier = threading.Barrier(2)

    def via_webhook():
        barrier.wait()
        results.append(webhook(client, {"id": "evt_b", "type": "checkout.session.completed",
                                        "data": {"object": {"id": "cs_test_both"}}}).status_code)

    def via_redirect():
        barrier.wait()
        results.append(client.get("/api/checkout/cs_test_both").status_code)

    threads = [threading.Thread(target=via_webhook), threading.Thread(target=via_redirect)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 200]
    assert count(Purchase) == 1 and count(BookingToken) == 1
    assert len(fakes["mailer"].sent) == 1


# --- refunds and tokens are scoped to their purchase -----------------------------------------


def refund(client, event_id, pi="pi_test_1", refunded=True):
    return webhook(client, {"id": event_id, "type": "charge.refunded",
                            "data": {"object": {"payment_intent": pi, "refunded": refunded}}})


def test_refund_only_revokes_its_own_purchase(client, fakes, token_for):
    mine = token_for("cs_test_1", email="a@example.com")
    other = token_for("cs_test_2", email="b@example.com")
    refund(client, "evt_r")
    assert client.get(f"/api/booking/{mine}").status_code == 404
    assert client.get(f"/api/booking/{other}").status_code == 200
    with SessionLocal() as db:
        statuses = dict(db.execute(select(Purchase.stripe_checkout_session_id, Purchase.payment_status)).all())
    assert statuses == {"cs_test_1": "refunded", "cs_test_2": "paid"}


def test_second_refund_event_keeps_first_revocation_time(client, token_for):
    token_for("cs_test_1")
    refund(client, "evt_r1")
    with SessionLocal() as db:
        first = db.scalar(select(BookingToken.revoked_at))
    assert abs(first - datetime.now(UTC)).total_seconds() < 60
    refund(client, "evt_r2")
    with SessionLocal() as db:
        assert db.scalar(select(BookingToken.revoked_at)) == first


def test_redirect_replay_returns_the_purchase_own_newest_token(client, fakes, token_for):
    t1 = token_for("cs_test_1", email="a@example.com")
    t2 = token_for("cs_test_2", email="b@example.com")
    assert client.get("/api/checkout/cs_test_1").json()["token"] == t1
    assert client.get("/api/checkout/cs_test_2").json()["token"] == t2
    with SessionLocal() as db:
        p1 = db.scalar(select(Purchase).where(Purchase.stripe_checkout_session_id == "cs_test_1"))
        db.add(BookingToken(purchase_id=p1.id, token="reissued-token"))
        db.commit()
    assert client.get("/api/checkout/cs_test_1").json()["token"] == "reissued-token"


# --- admin session isolation -----------------------------------------------------------------


@pytest.mark.parametrize("salt", [None, "other-feature"], ids=["default-salt", "other-salt"])
def test_cookie_signed_for_another_purpose_is_rejected(client, salt):
    kw = {} if salt is None else {"salt": salt}
    client.cookies.set("iaf_admin", URLSafeTimedSerializer("test-secret", **kw).dumps({"admin": True}), path="/api/admin")
    assert client.get("/api/admin/overview").status_code == 401


def test_missing_cookie_message(client):
    assert client.get("/api/admin/overview").json() == {"detail": "Authentification requise."}


# --- exact email contents ---------------------------------------------------------------------


def test_booking_emails_full_content(client, fakes, token_for):
    token = token_for("cs_test_1", hours=3, name="Marie Martin", email="marie@example.com")
    client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    mails = {m["subject"]: m for m in fakes["mailer"].sent}
    assert mails["Votre rendez-vous Conseil IA est confirmé"]["body"] == (
        "Bonjour,\n\nVotre première session de conseil IA est confirmée.\n\n"
        "Date :\nJeudi 8 octobre 2026\n\nHoraire :\n14h00 - 15h00\n"
        "Lien visio :\nhttps://meet.google.com/abc-defg-hij\n"
        "Vous avez acheté :\n3 heures de conseil\n\n"
        "Après cette première session :\n2 heures resteront à programmer.\n\n"
        "Une invitation calendrier vous a également été envoyée.\n\nÀ bientôt,\n\nSuan Tay\nIAfluence\n"
    )
    admin = mails["NOUVELLE RÉSERVATION — Conseil IA"]
    assert admin["to"] == "admin@iafluence.test"
    assert admin["body"] == (
        "Client :\nMarie Martin\n\nEmail :\nmarie@example.com\n\nPrestation :\nConseil IA - 3h\n\n"
        "Paiement :\nValidé (pi_test_1)\n\nRendez-vous :\n08/10/2026\n14:00 - 15:00\n"
        "Visio :\nhttps://meet.google.com/abc-defg-hij\n"
        "Heures achetées :\n3\n\nHeures restantes :\n2\n"
    )


def test_refund_alert_full_content(client, fakes, token_for):
    token = token_for("cs_test_1", name="Marie Martin", email="marie@example.com")
    client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    refund(client, "evt_r")
    alert = next(m for m in fakes["mailer"].sent if m["subject"] == "REMBOURSEMENT — Conseil IA")
    assert alert["body"] == (
        "Un remboursement Stripe a été reçu.\n\nClient :\nMarie Martin <marie@example.com>\n\n"
        "Prestation :\nConseil IA - 5h\n\nPaiement :\npi_test_1\n\nLe lien de réservation a été révoqué.\n"
        "ATTENTION : un rendez-vous est déjà planifié le 08/10/2026 14:00 - 15:00.\n"
        "Il n'a pas été annulé automatiquement — à traiter manuellement.\n"
    )
