"""End of session: finished sessions are closed and the link to book the next one is emailed (real PostgreSQL)."""

import asyncio
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import deps, main
from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, BookingToken, Customer, Purchase
from app.services import follow_up
from tests.conftest import staff_login, ADMIN_PASSWORD, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)
END = SLOT + timedelta(hours=1)
NEXT_SLOT = paris(2026, 10, 9, 10)
SUBJECT = "Réservez votre prochaine session de conseil IA"
THANKS = "Merci pour votre accompagnement Conseil IA"


def book(client, token, start=SLOT):
    r = client.post("/api/bookings", json={"token": token, "start": start.isoformat()})
    assert r.status_code == 201, r.text
    return r.json()


def statuses():
    with SessionLocal() as db:
        return list(db.scalars(select(Booking.status).order_by(Booking.id)))


def next_links(fakes):
    """Next-session emails, drafted (default) or sent."""
    mailer = fakes["mailer"]
    return [m for m in mailer.drafts + mailer.sent if m["subject"] == SUBJECT]


def set_auto_send(value: bool):
    with SessionLocal() as db:
        db.execute(update(Customer).values(auto_send_next_link=value))
        db.commit()


def test_nothing_happens_before_the_end_of_the_session(client, fakes, token_for):
    book(client, token_for(hours=3))
    assert follow_up.process_finished_sessions(fakes["mailer"], END - timedelta(seconds=1)) == 0
    assert statuses() == ["confirmed"] and next_links(fakes) == []


def test_link_to_next_session_is_drafted_once_at_the_end(client, fakes, token_for):
    token = token_for(hours=3, name="Marie Martin", email="marie@example.com")
    book(client, token)

    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 1
    assert statuses() == ["completed"]
    [mail] = fakes["mailer"].drafts
    assert mail["subject"] == SUBJECT
    assert all(m["subject"] != SUBJECT for m in fakes["mailer"].sent)
    assert mail["to"] == "marie@example.com"
    assert mail["body"] == (
        "Bonjour Marie Martin,\n\nMerci pour notre session de conseil IA.\n\n"
        "Il vous reste 2 heures de conseil. Vous pouvez dès maintenant choisir le créneau de votre prochaine "
        "session de 1 heure :\n\n"
        f"https://booking.iafluence.test/fr/reservation/{token}\n\n"
        "À bientôt,\n\nSuan Tay\nIAfluence\n"
    )

    assert follow_up.process_finished_sessions(fakes["mailer"], END + timedelta(minutes=5)) == 0
    assert len(next_links(fakes)) == 1


def test_the_same_link_books_the_next_session(client, fakes, token_for):
    token = token_for(hours=3)
    book(client, token)
    follow_up.process_finished_sessions(fakes["mailer"], END)

    ctx = client.get(f"/api/booking/{token}").json()
    assert ctx["booking"] is None
    assert ctx["purchase"] == {"product_name": "Conseil IA - 3h", "hours_purchased": 3, "hours_booked": 1, "hours_remaining": 2}
    assert client.get("/api/availability", params={"token": token}).json()["slots"]

    fakes["mailer"].sent.clear()
    confirmed = book(client, token, NEXT_SLOT)
    assert (confirmed["hours_booked"], confirmed["hours_remaining"]) == (2, 1)
    assert statuses() == ["completed", "confirmed"]
    confirmation = next(m for m in fakes["mailer"].sent if m["subject"] == "Votre rendez-vous Conseil IA est confirmé")
    assert confirmation["body"].startswith("Bonjour,\n\nVotre session de conseil IA est confirmée.\n")
    assert "Après cette session :\n1 heure restera à programmer.\nUn lien pour réserver" in confirmation["body"]

    # While the next session is upcoming, the link shows it and refuses a third booking.
    assert client.get(f"/api/booking/{token}").json()["booking"]["start"] == NEXT_SLOT.isoformat()
    r = client.post("/api/bookings", json={"token": token, "start": paris(2026, 10, 12, 10).isoformat()})
    assert r.status_code == 409 and r.json()["detail"] == "Votre prochaine session est déjà réservée."


def test_last_hour_drafts_a_thank_you_pointing_to_more_hours(client, fakes, token_for):
    token = token_for(hours=1, name="Marie Martin", email="marie@example.com")
    book(client, token)
    confirmation = next(m for m in fakes["mailer"].sent if m["subject"] == "Votre rendez-vous Conseil IA est confirmé")
    assert "Un lien pour réserver" not in confirmation["body"]

    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 1
    assert statuses() == ["completed"] and next_links(fakes) == []
    [mail] = fakes["mailer"].drafts
    assert (mail["to"], mail["subject"]) == ("marie@example.com", THANKS)
    assert mail["body"] == (
        "Bonjour Marie Martin,\n\nMerci pour notre dernière session de conseil IA et pour votre confiance.\n\n"
        "Votre accompagnement (1 heure de conseil) est maintenant terminé.\n\n"
        "Si vous souhaitez poursuivre avec de nouvelles heures de conseil, rendez-vous sur :\n\n"
        "https://iafluence.fr\n\n"
        "À bientôt,\n\nSuan Tay\nIAfluence\n"
    )
    assert all(m["subject"] != THANKS for m in fakes["mailer"].sent)

    assert follow_up.process_finished_sessions(fakes["mailer"], END + timedelta(minutes=5)) == 0
    assert len(fakes["mailer"].drafts) == 1
    r = client.post("/api/bookings", json={"token": token, "start": NEXT_SLOT.isoformat()})
    assert r.status_code == 409 and r.json()["code"] == "no_hours_left"


def test_thank_you_is_sent_directly_on_auto_send_with_the_configured_shop(client, fakes, token_for, monkeypatch):
    monkeypatch.setattr(get_config(), "shop_url", "https://iafluence.fr/conseil")
    book(client, token_for(hours=1))
    set_auto_send(True)
    follow_up.process_finished_sessions(fakes["mailer"], END)
    [mail] = [m for m in fakes["mailer"].sent if m["subject"] == THANKS]
    assert "https://iafluence.fr/conseil" in mail["body"].splitlines()
    assert fakes["mailer"].drafts == []


def test_refunded_purchase_gets_no_email(client, fakes, token_for):
    book(client, token_for(hours=1))
    with SessionLocal() as db:
        db.execute(update(Purchase).values(payment_status="refunded"))
        db.commit()
    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 0
    assert statuses() == ["completed"] and fakes["mailer"].drafts == []


def test_revoked_token_gets_no_link(client, fakes, token_for):
    book(client, token_for(hours=3))
    with SessionLocal() as db:
        db.execute(update(BookingToken).values(revoked_at=END))
        db.commit()
    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 0
    assert statuses() == ["completed"] and next_links(fakes) == []


def test_link_uses_the_newest_active_token(client, fakes, token_for):
    old = token_for(hours=3)
    book(client, old)
    with SessionLocal() as db:
        purchase_id = db.scalar(select(Purchase.id))
        db.execute(update(BookingToken).values(revoked_at=END))
        db.add(BookingToken(purchase_id=purchase_id, token="tok-new"))
        db.commit()
    follow_up.process_finished_sessions(fakes["mailer"], END)
    [mail] = next_links(fakes)
    assert "https://booking.iafluence.test/fr/reservation/tok-new" in mail["body"].splitlines()


@pytest.mark.parametrize("hours", [3, 1])
def test_long_finished_sessions_are_closed_silently(client, fakes, token_for, caplog, hours):
    book(client, token_for(hours=hours))
    late = END + follow_up.EMAIL_GRACE + timedelta(seconds=1)
    with caplog.at_level(logging.WARNING, logger="app.services.follow_up"):
        assert follow_up.process_finished_sessions(fakes["mailer"], late) == 0
    assert statuses() == ["completed"] and fakes["mailer"].drafts == []
    assert "closed without follow-up email" in caplog.text


def test_email_at_the_grace_limit_is_still_sent(client, fakes, token_for):
    book(client, token_for(hours=3))
    assert follow_up.process_finished_sessions(fakes["mailer"], END + follow_up.EMAIL_GRACE) == 1


def test_completed_sessions_count_as_delivered_hours(client, fakes, token_for):
    book(client, token_for(hours=3))
    follow_up.process_finished_sessions(fakes["mailer"], END)
    main.app.dependency_overrides[deps.get_now] = lambda: END
    staff_login(client)
    kpis = client.get("/api/consultant/overview").json()["kpis"]
    assert (kpis["hours_booked"], kpis["hours_done"]) == (1, 1.0)


def test_job_keeps_running_after_a_failure(monkeypatch, caplog):
    calls = []

    def fake(mailer, now):
        calls.append((mailer, now))
        if len(calls) == 1:
            raise RuntimeError("db down")
        if len(calls) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(follow_up, "process_finished_sessions", fake)
    with caplog.at_level(logging.ERROR, logger="app.services.follow_up"), pytest.raises(asyncio.CancelledError):
        asyncio.run(follow_up.run_forever(lambda: "mailer", 0))
    assert len(calls) == 3 and all(m == "mailer" and n.tzinfo is not None for m, n in calls)
    assert "end-of-session job failed" in caplog.text


def test_job_runs_with_the_app_only_when_enabled(monkeypatch):
    started = []

    async def fake_run_forever(mailer_factory, interval):
        started.append(interval)
        await asyncio.Event().wait()

    monkeypatch.setattr(follow_up, "run_forever", fake_run_forever)
    with TestClient(main.app):
        pass
    assert started == []

    monkeypatch.setattr(get_config(), "follow_up_poll_seconds", 60)
    with TestClient(main.app):
        pass
    assert started == [60]


def test_link_is_sent_directly_when_the_client_is_on_auto_send(client, fakes, token_for):
    book(client, token_for(hours=3))
    set_auto_send(True)
    follow_up.process_finished_sessions(fakes["mailer"], END)
    assert [m["subject"] for m in fakes["mailer"].sent if m["subject"] == SUBJECT] == [SUBJECT]
    assert fakes["mailer"].drafts == []
