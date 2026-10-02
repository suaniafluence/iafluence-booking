"""Admin: session report status and actions, « Connexion Codex » device login (real PostgreSQL)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app import deps, main
from app.config import get_config
from app.db import SessionLocal
from app.models import CodexLogin, Customer, Purchase, SessionReport
from app.services import follow_up, session_reports
from app.services.codex import CodexAccount
from app.services.session_reports import Gateways
from tests.conftest import ADMIN_PASSWORD, NOW, SYNTHESE, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)
END = SLOT + timedelta(hours=1)
CLIENT = "marie@example.com"


@pytest.fixture(autouse=True)
def reports_on(monkeypatch):
    monkeypatch.setattr(get_config(), "fireflies_api_key", "ff-key")
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")


@pytest.fixture
def admin(client):
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200
    return client


def at(when):
    main.app.dependency_overrides[deps.get_now] = lambda: when


@pytest.fixture
def ended(admin, fakes, token_for):
    """A session that ended at END, its report waiting for the transcript; the admin clock is END + 1 min."""
    token = token_for(hours=3, name="Marie Martin", email=CLIENT)
    assert admin.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()}).status_code == 201
    follow_up.process_finished_sessions(fakes["mailer"], END)
    fakes["mailer"].sent.clear()  # booking confirmations
    at(END + timedelta(minutes=1))
    with SessionLocal() as db:
        return db.scalar(select(SessionReport.id))


def report():
    with SessionLocal() as db:
        return db.scalar(select(SessionReport))


def set_report(**values):
    with SessionLocal() as db:
        db.execute(update(SessionReport).values(**values))
        db.commit()


def sessions(admin):
    return admin.get("/api/admin/overview").json()["reports"]


# --- overview ----------------------------------------------------------------------------------------------------


def test_overview_lists_finished_sessions_with_their_report(ended, admin, fakes):
    reports = sessions(admin)
    assert (reports["enabled"], reports["send_without_review"]) == (True, False)
    [row] = reports["sessions"]
    assert row == {
        "booking_id": 1,
        "kind": "session",
        "customer": "Marie Martin",
        "email": CLIENT,
        "product": "Conseil IA - 3h",
        "start": "2026-10-08T14:00:00+02:00",
        "end": "2026-10-08T15:00:00+02:00",
        "report": {
            "id": ended,
            "status": "waiting_transcript",
            "transcript_found": False,
            "transcript_attempts": 0,
            "summary_attempts": 0,
            "next_attempt_at": "2026-10-08T15:05:00+02:00",
            "waiting_until": "2026-10-08T21:00:00+02:00",
            "error": None,
            "synthese": None,
            "has_image": False,
            "delivery": None,
            "with_summary": None,
            "drafted_at": None,
            "erased": False,
        },
    }

    fakes["fireflies"].add("ff_1", SLOT, [CLIENT])
    session_reports.process(Gateways(fakes["mailer"], fakes["fireflies"], fakes["codex"]), END + timedelta(minutes=5))
    got = sessions(admin)["sessions"][0]["report"]
    assert (got["status"], got["synthese"], got["has_image"], got["delivery"], got["with_summary"]) == (
        "drafted",
        SYNTHESE,
        True,
        "draft",
        True,
    )
    assert got["drafted_at"] == "2026-10-08T15:05:00+02:00" and got["transcript_found"] is True


def test_sessions_without_report_and_upcoming_ones(admin, fakes, token_for, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    token = token_for(hours=3, email=CLIENT)
    admin.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    reports = sessions(admin)
    assert reports["enabled"] is False and reports["sessions"] == []  # still upcoming
    follow_up.process_finished_sessions(fakes["mailer"], END)
    [row] = sessions(admin)["sessions"]
    assert row["report"] is None


def test_report_endpoints_need_the_admin(client):
    for method, path in [
        ("get", "/api/admin/reports/1/image.png"),
        ("post", "/api/admin/reports/1/retry"),
        ("post", "/api/admin/reports/1/draft-without-summary"),
        ("post", "/api/admin/reports/1/retry-email"),
        ("patch", "/api/admin/report-settings"),
        ("get", "/api/admin/codex"),
        ("post", "/api/admin/codex/login"),
        ("get", "/api/admin/codex/login/1"),
        ("post", "/api/admin/codex/login/1/cancel"),
        ("post", "/api/admin/codex/logout"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_infographic_is_served_to_the_admin_only(ended, admin):
    assert admin.get(f"/api/admin/reports/{ended}/image.png").status_code == 404
    set_report(image_png=b"\x89PNG-fake")
    r = admin.get(f"/api/admin/reports/{ended}/image.png")
    assert (r.status_code, r.content, r.headers["content-type"]) == (200, b"\x89PNG-fake", "image/png")
    assert r.headers["cache-control"] == "private, no-store"


# --- actions -----------------------------------------------------------------------------------------------------


def test_retry_searches_fireflies_again_for_6_hours(ended, admin):
    set_report(status="failed", error="x", next_attempt_at=None, waiting_since=END - timedelta(hours=8))
    r = admin.post(f"/api/admin/reports/{ended}/retry")
    assert r.json() == {"id": ended, "status": "waiting_transcript"}
    got = report()
    assert (got.waiting_since, got.next_attempt_at, got.error) == (END + timedelta(minutes=1),) * 2 + (None,)


def test_retry_summarizes_again_when_the_transcript_was_found(ended, admin):
    set_report(status="failed", fireflies_transcript_id="ff_1", error="x", claimed_until=END)
    assert admin.post(f"/api/admin/reports/{ended}/retry").json()["status"] == "summarizing"
    got = report()
    assert (got.next_attempt_at, got.claimed_until, got.error, got.waiting_since) == (
        END + timedelta(minutes=1),
        None,
        None,
        END,
    )


@pytest.mark.parametrize(
    "values, message",
    [
        ({"status": "drafted"}, "L'email de cette séance a déjà été préparé."),
        ({"status": "ready"}, "L'email de cette séance a déjà été préparé."),
        (
            {"status": "summarizing", "claimed_until": END + timedelta(minutes=2)},
            "Le résumé est en cours de rédaction : réessayez dans quelques minutes.",
        ),
    ],
    ids=["drafted", "ready", "summarizing"],
)
def test_actions_are_refused_while_busy_or_done(ended, admin, fakes, values, message):
    set_report(**values)
    for action in ("retry", "draft-without-summary"):
        r = admin.post(f"/api/admin/reports/{ended}/{action}")
        assert (r.status_code, r.json()["detail"]) == (409, message)
    assert fakes["mailer"].drafts == []


def test_expired_claim_can_be_taken_over(ended, admin):
    set_report(status="summarizing", fireflies_transcript_id="ff_1", claimed_until=END)
    assert admin.post(f"/api/admin/reports/{ended}/retry").status_code == 200


def test_unknown_report(admin):
    for action in ("retry", "draft-without-summary"):
        r = admin.post(f"/api/admin/reports/999/{action}")
        assert (r.status_code, r.json()["detail"]) == (404, "Compte rendu introuvable.")


def test_draft_without_summary_is_always_a_draft(ended, admin, fakes):
    with SessionLocal() as db:
        db.execute(update(Customer).values(auto_send_next_link=True))
        db.commit()
    r = admin.post(f"/api/admin/reports/{ended}/draft-without-summary")
    assert r.json() == {"id": ended, "status": "drafted"}
    [mail] = fakes["mailer"].drafts
    assert (mail["to"], mail["subject"]) == (CLIENT, session_reports.SUBJECT_NEXT_V1)
    assert fakes["mailer"].sent == []
    got = report()
    assert (got.status, got.delivery, got.with_summary) == ("drafted", "draft", False)
    assert admin.post(f"/api/admin/reports/{ended}/draft-without-summary").status_code == 409


def test_draft_without_summary_on_a_refunded_purchase(ended, admin, fakes):
    with SessionLocal() as db:
        db.execute(update(Purchase).values(payment_status="refunded"))
        db.commit()
    r = admin.post(f"/api/admin/reports/{ended}/draft-without-summary")
    assert (r.status_code, r.json()["detail"]) == (409, "Achat remboursé : aucun email préparé.")
    assert report().status == "failed" and fakes["mailer"].drafts == []


def gmail_failed(fakes, ended):
    """The summary was written, then Gmail refused the draft."""
    set_report(status="ready", summary=SYNTHESE, fireflies_transcript_id="ff_1")
    fakes["mailer"].fail = True
    session_reports.draft_ready(fakes["mailer"], END + timedelta(minutes=1))
    fakes["mailer"].fail = False
    got = report()
    assert (got.status, got.delivery, got.error) == ("drafted", "failed", session_reports.GMAIL_FAILED)


def test_overview_shows_a_gmail_failure(ended, admin, fakes):
    gmail_failed(fakes, ended)
    got = sessions(admin)["sessions"][0]["report"]
    assert (got["status"], got["delivery"], got["error"]) == ("drafted", "failed", session_reports.GMAIL_FAILED)


def test_retry_email_prepares_the_same_email_again(ended, admin, fakes):
    gmail_failed(fakes, ended)
    at(END + timedelta(hours=2))
    r = admin.post(f"/api/admin/reports/{ended}/retry-email")
    assert r.json() == {"id": ended, "status": "drafted"}
    [mail] = fakes["mailer"].drafts
    assert (mail["to"], mail["subject"]) == (CLIENT, session_reports.SUBJECT_NEXT) and mail["html"]
    got = report()
    assert (got.status, got.delivery, got.with_summary, got.error) == ("drafted", "draft", True, None)
    assert got.drafted_at == END + timedelta(hours=2)
    # Done: a second click does nothing.
    r = admin.post(f"/api/admin/reports/{ended}/retry-email")
    assert (r.status_code, r.json()["detail"]) == (409, "Cet email n'a pas échoué : rien à recréer.")
    assert len(fakes["mailer"].drafts) == 1


def test_retry_email_fails_again(ended, admin, fakes):
    gmail_failed(fakes, ended)
    fakes["mailer"].fail = True
    assert admin.post(f"/api/admin/reports/{ended}/retry-email").status_code == 200
    got = report()
    assert (got.delivery, got.error) == ("failed", session_reports.GMAIL_FAILED)


def test_retry_email_without_summary_stays_without(ended, admin, fakes):
    set_report(status="drafted", delivery="failed", with_summary=False, summary=SYNTHESE)
    admin.post(f"/api/admin/reports/{ended}/retry-email")
    [mail] = fakes["mailer"].drafts
    assert mail["subject"] == session_reports.SUBJECT_NEXT_V1 and report().with_summary is False


def test_retry_email_on_a_refunded_purchase(ended, admin, fakes):
    gmail_failed(fakes, ended)
    with SessionLocal() as db:
        db.execute(update(Purchase).values(payment_status="refunded"))
        db.commit()
    r = admin.post(f"/api/admin/reports/{ended}/retry-email")
    assert (r.status_code, r.json()["detail"]) == (409, "Achat remboursé : aucun email préparé.")
    assert report().status == "failed" and fakes["mailer"].drafts == []


@pytest.mark.parametrize("values", [{"status": "waiting_transcript"}, {"status": "drafted", "delivery": "draft"}])
def test_retry_email_only_after_a_gmail_failure(ended, admin, fakes, values):
    set_report(**values)
    r = admin.post(f"/api/admin/reports/{ended}/retry-email")
    assert (r.status_code, r.json()["detail"]) == (409, "Cet email n'a pas échoué : rien à recréer.")
    assert admin.post("/api/admin/reports/999/retry-email").status_code == 404
    assert fakes["mailer"].drafts == []


def test_send_without_review_setting(admin):
    r = admin.patch("/api/admin/report-settings", json={"send_without_review": True})
    assert r.json() == {"send_without_review": True}
    assert sessions(admin)["send_without_review"] is True
    admin.patch("/api/admin/report-settings", json={"send_without_review": False})
    assert sessions(admin)["send_without_review"] is False
    assert admin.patch("/api/admin/report-settings", json={}).status_code == 422


# --- Codex connection --------------------------------------------------------------------------------------------

LOGIN_KEYS = {"id", "status", "verification_url", "user_code", "expires_at", "error"}


def logins():
    with SessionLocal() as db:
        return db.scalars(select(CodexLogin).order_by(CodexLogin.id)).all()


def test_codex_status_states(admin, fakes, monkeypatch):
    at(NOW)
    base = {"email": None, "plan": None, "detail": None, "pending_login": None}
    assert admin.get("/api/admin/codex").json() == base | {
        "state": "connected",
        "email": "suan@iafluence.fr",
        "plan": "plus",
    }
    fakes["codex"].connected = None
    assert admin.get("/api/admin/codex").json() == base | {"state": "disconnected"}
    fakes["codex"].unavailable = True
    assert admin.get("/api/admin/codex").json() == base | {
        "state": "unavailable",
        "detail": "codex app-server injoignable (ConnectionRefusedError)",
    }
    # Codex can be linked before Fireflies is set up.
    fakes["codex"].unavailable = False
    monkeypatch.setattr(get_config(), "fireflies_api_key", "")
    assert admin.get("/api/admin/codex").json() == base | {"state": "disconnected"}
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    assert admin.get("/api/admin/codex").json() == base | {"state": "not_configured"}


def test_device_login_completes_when_the_app_server_reports_it(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    r = admin.post("/api/admin/codex/login")
    assert r.status_code == 201
    login = r.json()
    assert login == {
        "id": 1,
        "status": "PENDING",
        "verification_url": "https://auth.openai.com/codex/device",
        "user_code": "ABCD-1234",
        "expires_at": "2026-10-05T06:15:00+00:00",
        "error": None,
    }
    assert admin.get("/api/admin/codex").json()["pending_login"]["id"] == 1

    # Still waiting for the admin to approve on the OpenAI page.
    assert admin.get("/api/admin/codex/login/1").json()["status"] == "PENDING"

    [(code, on_done)] = fakes["codex"].logins
    fakes["codex"].connected = CodexAccount("suan@iafluence.fr", "plus")
    on_done(code.login_id, "COMPLETED", None)
    got = admin.get("/api/admin/codex/login/1").json()
    assert got | {"expires_at": None} == {
        "id": 1,
        "status": "COMPLETED",
        "verification_url": None,
        "user_code": None,
        "expires_at": None,
        "error": None,
    }
    [row] = logins()
    assert row.user_code == "" and row.completed_at is not None
    assert admin.get("/api/admin/codex").json()["state"] == "connected"
    # A late duplicate outcome changes nothing.
    on_done(code.login_id, "ERROR", "late")
    assert logins()[0].status == "COMPLETED"


def test_status_check_completes_the_login_if_the_notification_was_lost(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    admin.post("/api/admin/codex/login")
    fakes["codex"].connected = CodexAccount("suan@iafluence.fr", "plus")
    assert admin.get("/api/admin/codex/login/1").json()["status"] == "COMPLETED"


def test_status_check_survives_an_unreachable_app_server(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    admin.post("/api/admin/codex/login")
    fakes["codex"].unavailable = True
    assert admin.get("/api/admin/codex/login/1").json()["status"] == "PENDING"


def test_device_code_expires_after_15_minutes(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    admin.post("/api/admin/codex/login")
    at(NOW + timedelta(minutes=15) - timedelta(seconds=1))
    assert admin.get("/api/admin/codex/login/1").json()["status"] == "PENDING"
    at(NOW + timedelta(minutes=15))
    assert admin.get("/api/admin/codex/login/1").json()["status"] == "EXPIRED"
    assert admin.get("/api/admin/codex").json()["pending_login"] is None


@pytest.mark.parametrize("outcome", ["DENIED", "ERROR", "EXPIRED"])
def test_failed_device_login(admin, fakes, outcome):
    at(NOW)
    fakes["codex"].connected = None
    admin.post("/api/admin/codex/login")
    [(code, on_done)] = fakes["codex"].logins
    on_done(code.login_id, outcome, "access_denied" if outcome == "DENIED" else None)
    got = admin.get("/api/admin/codex/login/1").json()
    assert (got["status"], got["user_code"]) == (outcome, None)
    assert got["error"] == ("access_denied" if outcome == "DENIED" else None)


def test_cancel_and_restart(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    admin.post("/api/admin/codex/login")
    r = admin.post("/api/admin/codex/login/1/cancel")
    assert r.json()["status"] == "CANCELLED" and fakes["codex"].cancelled == ["login-1"]
    # Cancelling twice is harmless.
    assert admin.post("/api/admin/codex/login/1/cancel").json()["status"] == "CANCELLED"
    assert fakes["codex"].cancelled == ["login-1"]

    # A new « Connecter Codex » replaces a pending one, on the app-server too.
    admin.post("/api/admin/codex/login")
    admin.post("/api/admin/codex/login")
    assert [login.status for login in logins()] == ["CANCELLED", "CANCELLED", "PENDING"]
    assert fakes["codex"].cancelled == ["login-1", "login-2"]

    fakes["codex"].unavailable = True
    assert admin.post("/api/admin/codex/login/3/cancel").json()["status"] == "CANCELLED"


def test_unknown_login_and_unreachable_app_server(admin, fakes):
    assert admin.get("/api/admin/codex/login/42").status_code == 404
    assert admin.post("/api/admin/codex/login/42/cancel").status_code == 404
    fakes["codex"].unavailable = True
    r = admin.post("/api/admin/codex/login")
    assert r.status_code == 502
    assert r.json()["detail"] == (
        "Le service Codex est injoignable : codex app-server injoignable (ConnectionRefusedError)"
    )
    assert admin.post("/api/admin/codex/logout").status_code == 502


def test_logout_and_expired_session(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    admin.post("/api/admin/codex/login")
    [(code, on_done)] = fakes["codex"].logins
    on_done(code.login_id, "COMPLETED", None)

    # The ChatGPT session ended on its own (refresh refused): shown as expired.
    assert admin.get("/api/admin/codex").json()["state"] == "expired"

    fakes["codex"].connected = CodexAccount("suan@iafluence.fr", "plus")
    assert admin.post("/api/admin/codex/logout").json() == {"state": "disconnected"}
    assert fakes["codex"].logged_out == 1 and logins()[0].ended_at == NOW
    assert admin.get("/api/admin/codex").json()["state"] == "disconnected"


def test_no_secret_ever_reaches_the_browser(admin, fakes):
    at(NOW)
    fakes["codex"].connected = None
    bodies = [admin.post("/api/admin/codex/login").text, admin.get("/api/admin/codex").text]
    bodies.append(admin.get("/api/admin/codex/login/1").text)
    for body in bodies:
        for word in ("token", "access", "refresh", "secret", "password", "ws://"):
            assert word not in body.lower(), (word, body)
