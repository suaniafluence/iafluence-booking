"""Admin: cancelling / moving a session and adjusting a purchase's hours (real PostgreSQL)."""

import pytest
from sqlalchemy import select, update

from app import deps
from app.db import SessionLocal
from app.main import app
from app.models import Booking, BookingToken, Purchase
from app.services.calendar_service import CalendarWriteError
from tests.conftest import ADMIN_PASSWORD, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)
CANCELLED = "Votre session de conseil IA a été annulée"


def login(client):
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200


def booked(client, token_for, hours=3, **kw):
    token = token_for(hours=hours, **kw)
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        return token, db.scalar(select(Booking.id))


def booking_row(booking_id):
    with SessionLocal() as db:
        b = db.get(Booking, booking_id)
        return b.status, b.purchase.hours_booked


def test_endpoints_require_the_admin_session(client):
    assert client.post("/api/admin/bookings/1/cancel", json={}).status_code == 401
    assert client.patch("/api/admin/purchases/1", json={"hours_purchased": 2}).status_code == 401


def test_cancel_gives_the_hour_back_deletes_the_event_and_emails_the_link(client, fakes, token_for):
    token, booking_id = booked(client, token_for, name="Marie Martin", email="marie@example.com")
    login(client)
    assert client.get("/api/admin/overview").json()["upcoming"][0]["booking_id"] == booking_id
    fakes["mailer"].sent.clear()

    r = client.post(f"/api/admin/bookings/{booking_id}/cancel", json={})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "cancelled", "hours_purchased": 3, "hours_booked": 0, "hours_remaining": 3}
    assert booking_row(booking_id) == ("cancelled", 0)
    assert fakes["calendar"].deleted == ["evt_1"] and fakes["calendar"].deleted_from == ["booking-cal"]

    [mail] = fakes["mailer"].sent
    assert (mail["to"], mail["subject"]) == ("marie@example.com", CANCELLED)
    assert mail["body"] == (
        "Bonjour Marie Martin,\n\nVotre session de conseil IA du Jeudi 8 octobre 2026 (14h00 - 15h00) a été annulée. "
        "L'heure correspondante vous a été recréditée.\n\nVous pouvez choisir un nouveau créneau ici :\n\n"
        f"https://booking.iafluence.test/reservation/{token}\n\nÀ bientôt,\n\nSuan Tay\nIAfluence\n"
    )

    # The slot is free again and the client can book it (or another one) with the same link.
    assert client.get(f"/api/booking/{token}").json()["booking"] is None
    fakes["calendar"].events.clear()
    again = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert again.status_code == 201 and again.json()["hours_booked"] == 1
    assert client.get("/api/admin/overview").json()["upcoming"][0]["booking_id"] != booking_id


def test_cancel_without_notifying_the_client(client, fakes, token_for):
    _, booking_id = booked(client, token_for)
    login(client)
    fakes["mailer"].sent.clear()
    assert client.post(f"/api/admin/bookings/{booking_id}/cancel", json={"notify": False}).status_code == 200
    assert fakes["mailer"].sent == [] and booking_row(booking_id) == ("cancelled", 0)


def test_cancel_of_a_revoked_purchase_sends_nothing(client, fakes, token_for):
    _, booking_id = booked(client, token_for)
    with SessionLocal() as db:
        db.execute(update(BookingToken).values(revoked_at=SLOT))
        db.commit()
    login(client)
    fakes["mailer"].sent.clear()
    assert client.post(f"/api/admin/bookings/{booking_id}/cancel", json={}).status_code == 200
    assert fakes["mailer"].sent == []


def test_cancel_when_google_fails_changes_nothing(client, fakes, token_for, monkeypatch):
    _, booking_id = booked(client, token_for)

    def boom(calendar_id, event_id):
        raise CalendarWriteError("quota")

    monkeypatch.setattr(fakes["calendar"], "delete_event", boom)
    login(client)
    r = client.post(f"/api/admin/bookings/{booking_id}/cancel", json={})
    assert r.status_code == 502 and r.json()["code"] == "calendar_delete_failed"
    assert "Rien n’a été annulé" in r.json()["detail"]
    assert booking_row(booking_id) == ("confirmed", 1)


def test_booking_without_google_event_can_be_cancelled(client, fakes, token_for):
    _, booking_id = booked(client, token_for)
    with SessionLocal() as db:
        db.execute(update(Booking).values(google_event_id=None))
        db.commit()
    login(client)
    assert client.post(f"/api/admin/bookings/{booking_id}/cancel", json={}).status_code == 200
    assert fakes["calendar"].deleted == []


def test_cannot_cancel_unknown_finished_or_already_cancelled_sessions(client, fakes, token_for):
    _, booking_id = booked(client, token_for)
    login(client)
    r = client.post("/api/admin/bookings/999/cancel", json={})
    assert r.status_code == 404 and r.json()["detail"] == "Séance introuvable."

    # Session over (still 'confirmed' until the end-of-session job runs).
    app.dependency_overrides[deps.get_now] = lambda: SLOT.replace(hour=15)
    r = client.post(f"/api/admin/bookings/{booking_id}/cancel", json={})
    assert r.status_code == 409 and r.json()["code"] == "not_cancellable"

    # In progress: still cancellable.
    app.dependency_overrides[deps.get_now] = lambda: SLOT.replace(minute=30)
    assert client.post(f"/api/admin/bookings/{booking_id}/cancel", json={}).status_code == 200
    r = client.post(f"/api/admin/bookings/{booking_id}/cancel", json={})
    assert r.status_code == 409 and r.json()["detail"] == "Seule une séance à venir ou en cours peut être annulée."
    assert booking_row(booking_id) == ("cancelled", 0)


def test_adjust_hours_after_a_partial_refund_or_extra_hours(client, token_for):
    token, _ = booked(client, token_for, hours=5)
    login(client)
    with SessionLocal() as db:
        purchase_id = db.scalar(select(Purchase.id))

    r = client.patch(f"/api/admin/purchases/{purchase_id}", json={"hours_purchased": 2})
    assert r.json() == {"hours_purchased": 2, "hours_booked": 1, "hours_remaining": 1}
    assert client.get(f"/api/booking/{token}").json()["purchase"]["hours_purchased"] == 2

    assert client.patch(f"/api/admin/purchases/{purchase_id}", json={"hours_purchased": 8}).json()["hours_remaining"] == 7
    assert client.patch(f"/api/admin/purchases/{purchase_id}", json={"hours_purchased": 1}).json()["hours_remaining"] == 0


def test_hours_cannot_go_below_what_is_already_booked(client, token_for):
    booked(client, token_for, hours=3)
    login(client)
    with SessionLocal() as db:
        purchase_id = db.scalar(select(Purchase.id))
    r = client.patch(f"/api/admin/purchases/{purchase_id}", json={"hours_purchased": 0})
    assert r.status_code == 422
    assert r.json()["detail"] == "Impossible : 1 h sont déjà réservées ou réalisées pour ce client."
    with SessionLocal() as db:
        assert db.get(Purchase, purchase_id).hours_purchased == 3


@pytest.mark.parametrize("hours", [-1, 101])
def test_hours_are_validated(client, token_for, hours):
    token_for()
    login(client)
    assert client.patch("/api/admin/purchases/1", json={"hours_purchased": hours}).status_code == 422


def test_adjust_hours_of_unknown_purchase(client):
    login(client)
    r = client.patch("/api/admin/purchases/999", json={"hours_purchased": 2})
    assert r.status_code == 404 and r.json()["detail"] == "Achat introuvable."


def test_zero_hours_on_an_untouched_purchase(client, token_for):
    token = token_for(hours=2)
    login(client)
    assert client.patch("/api/admin/purchases/1", json={"hours_purchased": 0}).json()["hours_remaining"] == 0
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert r.status_code == 409 and r.json()["code"] == "no_hours_left"
