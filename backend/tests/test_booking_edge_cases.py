"""Booking failure paths and races (real PostgreSQL)."""

import logging

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DataError

from app.db import SessionLocal
from app.models import Booking, Purchase, Settings
from app.services import booking_service
from app.services.calendar_service import CreatedEvent
from tests.conftest import NOW, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)


def post(client, token, start=SLOT):
    return client.post("/api/bookings", json={"token": token, "start": start.isoformat()})


def purchase_row():
    with SessionLocal() as db:
        return db.scalar(select(Purchase))


def set_purchase(**values):
    with SessionLocal() as db:
        db.execute(update(Purchase).values(**values))
        db.commit()


def test_no_hours_left(client, fakes, token_for):
    token = token_for(hours=2)
    set_purchase(hours_booked=2)
    r = post(client, token)
    assert r.status_code == 409
    assert r.json() == {"detail": "Toutes vos heures ont déjà été planifiées.", "code": "no_hours_left"}
    assert fakes["calendar"].events == []


def test_calendar_unavailable_during_booking(client, fakes, token_for):
    token = token_for()
    fakes["calendar"].errors.add("booking-cal")
    r = post(client, token)
    assert r.status_code == 503
    assert r.json()["code"] == "calendar_unavailable"
    assert fakes["calendar"].events == []
    assert purchase_row().hours_booked == 0


def test_booking_bypasses_listing_cache_and_checks_padded_slot(client, fakes, token_for):
    token = token_for()
    client.get("/api/availability", params={"token": token})
    calls_before = len(fakes["calendar"].freebusy_calls)
    assert post(client, token).status_code == 201
    assert len(fakes["calendar"].freebusy_calls) == calls_before + 1
    assert sorted(fakes["calendar"].freebusy_calls[-1]) == ["booking-cal", "cal-formation", "cal-principal"]


def test_busy_in_buffer_blocks_booking(client, fakes, token_for):
    token = token_for()
    # Ends 5 min into the 15-minute buffer before 14:00.
    fakes["calendar"].busy["cal-principal"] = [(paris(2026, 10, 8, 13), paris(2026, 10, 8, 13, 50))]
    assert post(client, token).json()["code"] == "slot_taken"


def test_event_uses_checkout_session_when_no_payment_intent(client, fakes, token_for):
    fakes["stripe"].add_session("cs_test_nopi")["payment_intent"] = None
    token = client.get("/api/checkout/cs_test_nopi").json()["token"]
    assert post(client, token).status_code == 201
    assert fakes["calendar"].events[0]["description"].endswith("Paiement Stripe :\ncs_test_nopi")
    admin = next(m for m in fakes["mailer"].sent if m["subject"].startswith("NOUVELLE"))
    assert "Validé (cs_test_nopi)" in admin["body"]


def test_meet_disabled(client, fakes, token_for):
    with SessionLocal() as db:
        db.execute(update(Settings).values(meet_enabled=False))
        db.commit()
    token = token_for(hours=2)
    body = post(client, token).json()
    assert body["meet_url"] is None
    assert fakes["calendar"].events[0]["with_meet"] is False
    confirm = next(m for m in fakes["mailer"].sent if m["subject"].startswith("Votre rendez-vous"))
    assert "Lien visio" not in confirm["body"]
    assert "1 heure restera à programmer" in confirm["body"]
    assert "2 heures de conseil" in confirm["body"]


def test_event_is_written_in_local_timezone(client, fakes, token_for):
    post(client, token_for())
    ev = fakes["calendar"].events[0]
    assert ev["start"].isoformat() == "2026-10-08T14:00:00+02:00"
    assert ev["end"].isoformat() == "2026-10-08T15:00:00+02:00"
    assert ev["timezone"] == "Europe/Paris"
    assert ev["attendee_name"] == "Jean Dupont"
    assert ev["description"].startswith("Session de conseil IA.\n\nHeures achetées : 5 h\nSession réservée : 1 h\n")


# --- races resolved inside the lock -------------------------------------------------------


def _during_slot_check(monkeypatch, action):
    """Run `action` after the pre-checks, right before the critical section starts."""
    real = booking_service.resolve_slot

    def wrapper(*a, **kw):
        action()
        return real(*a, **kw)

    monkeypatch.setattr(booking_service, "resolve_slot", wrapper)


def test_refund_racing_the_booking_is_refused(client, fakes, token_for, monkeypatch):
    token = token_for()
    _during_slot_check(monkeypatch, lambda: set_purchase(payment_status="refunded"))
    r = post(client, token)
    assert r.status_code == 404 and r.json()["code"] == "invalid_token"
    assert fakes["calendar"].events == []


def test_hours_used_up_racing_the_booking(client, fakes, token_for, monkeypatch):
    token = token_for(hours=1)
    _during_slot_check(monkeypatch, lambda: set_purchase(hours_booked=1))
    assert post(client, token).json()["code"] == "no_hours_left"
    assert fakes["calendar"].events == []


def test_parallel_booking_same_purchase_detected_inside_lock(client, fakes, token_for, monkeypatch):
    token = token_for()

    def other_tab_books():
        p = purchase_row()
        with SessionLocal() as db:
            db.add(Booking(purchase_id=p.id, customer_id=p.customer_id, start_datetime=paris(2026, 10, 9, 10),
                           end_datetime=paris(2026, 10, 9, 11), status="confirmed"))
            db.commit()

    _during_slot_check(monkeypatch, other_tab_books)
    r = post(client, token)
    assert r.status_code == 409 and r.json()["code"] == "already_booked"
    assert r.json()["booking"]["start"].startswith("2026-10-09T08:00:00")
    assert fakes["calendar"].events == []


# --- compensation when the DB refuses the booking after the event was created ------------


def _hide_db_bookings(monkeypatch):
    monkeypatch.setattr(booking_service, "db_busy", lambda db, rng: [])


def _insert_overlapping_booking(token_for):
    token_for("cs_test_other", email="other@example.com", name="Other")
    with SessionLocal() as db:
        other = db.scalar(select(Purchase).where(Purchase.stripe_checkout_session_id == "cs_test_other"))
        db.add(Booking(purchase_id=other.id, customer_id=other.customer_id, start_datetime=paris(2026, 10, 8, 14, 30),
                       end_datetime=paris(2026, 10, 8, 15, 30), status="confirmed"))
        db.commit()


def test_exclusion_constraint_violation_deletes_the_orphan_event(client, fakes, token_for, monkeypatch):
    token = token_for()
    _insert_overlapping_booking(token_for)
    _hide_db_bookings(monkeypatch)
    r = post(client, token)
    assert r.status_code == 409 and r.json()["code"] == "slot_taken"
    assert fakes["calendar"].deleted == ["evt_1"]
    assert fakes["calendar"].deleted_from == ["booking-cal"]
    with SessionLocal() as db:
        mine = db.scalar(select(Purchase).where(Purchase.stripe_checkout_session_id == "cs_test_1"))
        assert mine.hours_booked == 0
        assert db.scalar(select(func.count(Booking.id))) == 1


def test_failed_compensation_is_logged_for_manual_cleanup(client, fakes, token_for, monkeypatch, caplog):
    token = token_for()
    _insert_overlapping_booking(token_for)
    _hide_db_bookings(monkeypatch)

    def boom(calendar_id, event_id):
        raise RuntimeError("google down")

    monkeypatch.setattr(fakes["calendar"], "delete_event", boom)
    assert post(client, token).json()["code"] == "slot_taken"
    assert "could not delete orphan event evt_1" in caplog.text


def test_unexpected_db_error_compensates_and_propagates(client, fakes, token_for, caplog):
    token = token_for()

    class LongIdCalendar(type(fakes["calendar"])):
        def create_event(self, calendar_id, **kw):
            super().create_event(calendar_id, **kw)
            return CreatedEvent(event_id="x" * 300, meet_url=None)  # google_event_id is VARCHAR(255)

    cal = LongIdCalendar()
    with SessionLocal() as db, pytest.raises(DataError):
        booking_service.book(db, cal, token, SLOT, NOW)
    assert cal.deleted == ["x" * 300]
    assert purchase_row().hours_booked == 0


def test_successful_booking_clears_listing_cache(client, fakes, token_for):
    from app.services.calendar_service import freebusy_cache

    t1 = token_for("cs_test_a", email="a@example.com")
    t2 = token_for("cs_test_b", email="b@example.com")
    client.get("/api/availability", params={"token": t2})
    assert len(freebusy_cache._entries) == 1
    assert post(client, t1).status_code == 201
    assert freebusy_cache._entries == {}
    starts = [s["start"] for s in client.get("/api/availability", params={"token": t2}).json()["slots"]]
    # 14:00 booked + buffers -> 13:00 and 15:00 are gone too.
    for hh in ("13", "14", "15"):
        assert f"2026-10-08T{hh}:00:00+02:00" not in starts
    assert "2026-10-08T12:00:00+02:00" in starts and "2026-10-08T16:00:00+02:00" in starts


def test_booking_logs_confirmation(client, token_for, caplog):
    caplog.set_level(logging.INFO, logger="app.services.booking_service")
    post(client, token_for())
    assert "confirmed for purchase" in caplog.text


# --- availability listing -------------------------------------------------------------------


def test_availability_from_to_window(client, fakes, token_for):
    token = token_for()
    r = client.get("/api/availability", params={"token": token, "from": "2026-10-07T00:00:00+02:00", "to": "2026-10-08T00:00:00+02:00"})
    starts = [s["start"] for s in r.json()["slots"]]
    assert starts[0] == "2026-10-07T09:00:00+02:00" and starts[-1] == "2026-10-07T17:00:00+02:00"
    assert len(starts) == 9


def test_availability_inverted_window_skips_google(client, fakes, token_for):
    token = token_for()
    r = client.get("/api/availability", params={"token": token, "from": "2026-10-09T00:00:00+02:00", "to": "2026-10-08T00:00:00+02:00"})
    assert r.json() == {"slots": []}
    assert fakes["calendar"].freebusy_calls == []


def test_availability_rejects_naive_from(client, token_for):
    r = client.get("/api/availability", params={"token": token_for(), "from": "2026-10-07T00:00:00"})
    assert r.status_code == 422


def test_availability_for_refunded_purchase(client, token_for):
    token = token_for()
    set_purchase(payment_status="refunded")
    assert client.get("/api/availability", params={"token": token}).status_code == 404
    assert client.get(f"/api/booking/{token}").status_code == 404


def test_booking_context_payload(client, token_for):
    token = token_for(hours=3, name="Marie Martin", email="Marie@Example.com")
    assert client.get(f"/api/booking/{token}").json() == {
        "customer": {"name": "Marie Martin", "email": "marie@example.com"},
        "purchase": {"product_name": "Conseil IA - 3h", "hours_purchased": 3, "hours_booked": 0, "hours_remaining": 3},
        "booking": None,
        "consultant_name": "Suan Tay",
        "timezone": "Europe/Paris",
        "booking_duration_min": 60,
        "locale": "fr",
        "nda_available": False,
        "nda_sent": False,
    }

# --- the database is the source of truth while Google free/busy lags -----------------------


def test_database_blocks_slot_while_google_lags(client, fakes, token_for):
    fakes["calendar"].mirror_events = False  # the new event is not yet visible in free/busy
    t1 = token_for("cs_test_a", email="a@example.com")
    t2 = token_for("cs_test_b", email="b@example.com")
    assert post(client, t1).status_code == 201
    starts = [s["start"] for s in client.get("/api/availability", params={"token": t2}).json()["slots"]]
    for hh in ("13", "14", "15"):  # the booking and both buffers
        assert f"2026-10-08T{hh}:00:00+02:00" not in starts
    assert "2026-10-08T12:00:00+02:00" in starts and "2026-10-08T16:00:00+02:00" in starts
    assert post(client, t2).json()["code"] == "slot_taken"
    assert post(client, t2, paris(2026, 10, 8, 15)).json()["code"] == "slot_taken"
    assert len(fakes["calendar"].events) == 1


def test_cancelled_booking_does_not_block(client, fakes, token_for):
    fakes["calendar"].mirror_events = False
    token_for("cs_test_old", email="old@example.com")
    old = purchase_row()
    with SessionLocal() as db:
        db.add(Booking(purchase_id=old.id, customer_id=old.customer_id, start_datetime=SLOT,
                       end_datetime=paris(2026, 10, 8, 15), status="cancelled"))
        db.commit()
    token = token_for("cs_test_new", email="new@example.com")
    assert SLOT.isoformat() in [s["start"] for s in client.get("/api/availability", params={"token": token}).json()["slots"]]
    assert post(client, token).status_code == 201


def test_back_to_back_bookings_without_buffers(client, fakes, token_for):
    """Bookings ending exactly when the slot starts (or starting when it ends) do not overlap it."""
    fakes["calendar"].mirror_events = False
    with SessionLocal() as db:
        db.execute(update(Settings).values(buffer_before_min=0, buffer_after_min=0))
        db.commit()
    tokens = [token_for(f"cs_test_{i}", email=f"c{i}@example.com") for i in range(3)]
    assert post(client, tokens[0], paris(2026, 10, 8, 14)).status_code == 201
    assert post(client, tokens[1], paris(2026, 10, 8, 16)).status_code == 201
    starts = [s["start"] for s in client.get("/api/availability", params={"token": tokens[2]}).json()["slots"]]
    assert "2026-10-08T15:00:00+02:00" in starts
    assert post(client, tokens[2], paris(2026, 10, 8, 15)).status_code == 201


def test_final_check_covers_the_buffer_after_the_slot(client, fakes, token_for):
    token = token_for()
    # Starts 10 min into the 15-minute buffer after 15:00.
    fakes["calendar"].busy["cal-formation"] = [(paris(2026, 10, 8, 15, 10), paris(2026, 10, 8, 15, 30))]
    assert post(client, token).json()["code"] == "slot_taken"


def test_final_check_queries_exactly_the_padded_slot(client, fakes, token_for, monkeypatch):
    calls = []
    real = fakes["calendar"].free_busy
    monkeypatch.setattr(fakes["calendar"], "free_busy", lambda ids, a, b: calls.append((a, b)) or real(ids, a, b))
    assert post(client, token_for()).status_code == 201
    assert calls == [(paris(2026, 10, 8, 13, 45), paris(2026, 10, 8, 15, 15))]


def test_booking_context_after_booking(client, token_for):
    token = token_for(hours=2)
    post(client, token)
    ctx = client.get(f"/api/booking/{token}").json()
    assert ctx["booking"] == {
        "start": "2026-10-08T14:00:00+02:00",
        "end": "2026-10-08T15:00:00+02:00",
        "meet_url": "https://meet.google.com/abc-defg-hij",
    }
    assert ctx["purchase"] == {"product_name": "Conseil IA - 2h", "hours_purchased": 2, "hours_booked": 1, "hours_remaining": 1}


def test_already_booked_takes_precedence_and_returns_the_booking(client, token_for):
    token = token_for()
    post(client, token)
    r = post(client, token, paris(2026, 10, 8, 14, 30))  # an invalid slot, but the purchase is already used
    assert r.status_code == 409
    assert r.json()["booking"] == {
        "start": "2026-10-08T12:00:00+00:00",
        "end": "2026-10-08T13:00:00+00:00",
        "meet_url": "https://meet.google.com/abc-defg-hij",
    }


def test_availability_empty_window_skips_google(client, fakes, token_for):
    token = token_for()
    at = "2026-10-08T00:00:00+02:00"
    assert client.get("/api/availability", params={"token": token, "from": at, "to": at}).json() == {"slots": []}
    assert fakes["calendar"].freebusy_calls == []


def test_compensation_deletes_from_the_booking_calendar(client, fakes, token_for, monkeypatch):
    token = token_for()
    _insert_overlapping_booking(token_for)
    _hide_db_bookings(monkeypatch)
    post(client, token)
    assert fakes["calendar"].deleted_from == ["booking-cal"]
