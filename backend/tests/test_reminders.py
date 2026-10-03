"""Inactivity reminders (real PostgreSQL)."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import BookingToken, Customer, Settings
from app.services import follow_up, reminders
from tests.conftest import NOW
from tests.test_cockpit import add_booking, add_customer, add_purchase

pytestmark = pytest.mark.usefixtures("db_clean")


def emails(fakes):
    return fakes["mailer"].drafts + fakes["mailer"].sent


def set_settings(**values):
    with SessionLocal() as db:
        db.execute(update(Settings).values(**values))
        db.commit()


def learner(last_session_days_ago: int, hours=3, sessions=1, email="jean@example.com", locale="fr") -> int:
    cid = add_customer("Jean Dupont", email)
    pid = add_purchase(cid, hours, created=NOW - timedelta(days=last_session_days_ago + 10))
    with SessionLocal() as db:
        from app.models import Purchase

        db.execute(update(Purchase).where(Purchase.id == pid).values(locale=locale))
        db.commit()
    for i in range(sessions):
        add_booking(cid, NOW - timedelta(days=last_session_days_ago + 7 * i, hours=1), purchase_id=pid)
    return cid


def test_hours_left_the_reminder_carries_the_booking_link(fakes):
    cid = learner(21)
    assert reminders.process(fakes["mailer"], NOW) == 1
    [draft] = fakes["mailer"].drafts
    assert (draft["to"], draft["subject"]) == ("jean@example.com", "Où en êtes-vous ? Votre prochaine session de conseil IA")
    assert "Il vous reste 2 heures de conseil." in draft["body"]
    assert "https://booking.iafluence.test/fr/reservation/tok-1" in draft["body"]
    assert draft["body"].endswith("Suan Tay\nIAfluence\n")
    with SessionLocal() as db:
        assert db.get(Customer, cid).reminder_sent_at == NOW
    # Once per idle period.
    assert reminders.process(fakes["mailer"], NOW + timedelta(days=5)) == 0


def test_a_new_session_opens_a_new_period(fakes):
    cid = learner(21)
    reminders.process(fakes["mailer"], NOW)
    with SessionLocal() as db:
        pid = db.scalar(select(BookingToken.purchase_id))
    add_booking(cid, NOW + timedelta(days=1), purchase_id=pid)
    later = NOW + timedelta(days=23)
    assert reminders.process(fakes["mailer"], later) == 1


def test_not_before_the_delay_nor_after_the_hiding_one(fakes):
    learner(20, email="tot@example.com")
    learner(60, email="parti@example.com")
    assert reminders.process(fakes["mailer"], NOW) == 0


def test_no_reminder_with_a_session_booked(fakes):
    cid = learner(30)
    with SessionLocal() as db:
        pid = db.scalar(select(BookingToken.purchase_id))
    add_booking(cid, NOW + timedelta(days=2), purchase_id=pid, status="confirmed")
    assert reminders.process(fakes["mailer"], NOW) == 0


def test_programme_finished(fakes):
    learner(25, hours=1, sessions=1, locale="en")
    reminders.process(fakes["mailer"], NOW)
    [draft] = fakes["mailer"].drafts
    assert draft["subject"] == "How is your AI project going?"
    assert "https://iafluence.fr" in draft["body"]


def test_prospect_after_a_discovery_call(fakes):
    cid = add_customer("Paul", "paul@example.com")
    add_booking(cid, NOW - timedelta(days=22), kind="discovery", minutes=30)
    with SessionLocal() as db:
        from app.models import Booking

        db.execute(update(Booking).values(locale="es"))
        db.commit()
    reminders.process(fakes["mailer"], NOW)
    [draft] = fakes["mailer"].drafts
    assert draft["subject"] == "Tras nuestra llamada de descubrimiento"


def test_spanish_singular(fakes):
    learner(21, hours=2, sessions=1, locale="es")
    reminders.process(fakes["mailer"], NOW)
    assert "Le queda 1 hora de asesoría." in fakes["mailer"].drafts[0]["body"]


def test_auto_send(fakes):
    set_settings(reminder_auto_send=True)
    learner(21)
    reminders.process(fakes["mailer"], NOW)
    assert len(fakes["mailer"].sent) == 1 and fakes["mailer"].drafts == []


def test_disabled(fakes):
    set_settings(reminder_enabled=False)
    learner(21)
    assert reminders.process(fakes["mailer"], NOW) == 0


def test_nothing_to_say_still_closes_the_period(fakes):
    """A contact who only received the NDA, or a revoked link: marked handled, no email."""
    cid = learner(21)
    with SessionLocal() as db:
        db.execute(update(BookingToken).values(revoked_at=NOW))
        db.commit()
    contact = add_customer("Contact", "c@example.com")
    with SessionLocal() as db:
        db.execute(update(Customer).where(Customer.id == contact).values(created_at=NOW - timedelta(days=30)))
        db.commit()
    assert reminders.process(fakes["mailer"], NOW) == 0
    with SessionLocal() as db:
        assert db.get(Customer, cid).reminder_sent_at == NOW


def test_shown_in_the_cockpit(client, fakes):
    from tests.conftest import staff_login

    learner(25)
    reminders.process(fakes["mailer"], NOW)
    staff_login(client)
    [row] = client.get("/api/consultant/learners").json()["learners"]
    assert row["reminder_sent_at"] == "2026-10-05T08:00:00+02:00"
    assert {"niveau": "info", "texte": "Relancé, sans réponse pour l'instant"} in row["alerts"]


def test_follow_up_loop_runs_the_reminders_hourly(monkeypatch):
    calls = []
    monkeypatch.setattr(follow_up, "process_finished_sessions", lambda mailer, now: 0)
    monkeypatch.setattr(reminders, "process", lambda mailer, now: calls.append(now))

    async def main():
        task = asyncio.create_task(follow_up.run_forever(lambda: None, 0.01))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(main())
    assert len(calls) == 1


def test_follow_up_loop_survives_a_reminder_failure(monkeypatch, caplog):
    monkeypatch.setattr(follow_up, "process_finished_sessions", lambda mailer, now: 0)

    def boom(mailer, now):
        raise RuntimeError("x")

    monkeypatch.setattr(reminders, "process", boom)

    async def main():
        task = asyncio.create_task(follow_up.run_forever(lambda: None, 0.01))
        for _ in range(500):
            if "inactivity reminder job failed" in caplog.text:
                break
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(main())
    assert "inactivity reminder job failed" in caplog.text
