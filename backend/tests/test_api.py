import json
import threading

import pytest

from tests.conftest import staff_login, ADMIN_PASSWORD, NOW, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)  # Thursday 8 Oct 14:00


def webhook(client, event: dict, signature="valid-signature"):
    return client.post(
        "/webhooks/stripe", content=json.dumps(event), headers={"stripe-signature": signature}
    )


def checkout_event(event_id: str, session_id: str) -> dict:
    return {"id": event_id, "type": "checkout.session.completed", "data": {"object": {"id": session_id}}}


# --- payment -> token --------------------------------------------------------------


def test_checkout_exchange_creates_purchase_and_emails_link(client, fakes):
    fakes["stripe"].add_session("cs_test_1", hours=5)
    r = client.get("/api/checkout/cs_test_1")
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["locale"] == "fr"
    assert len(token) >= 40
    assert "cs_test_1" not in token

    ctx = client.get(f"/api/booking/{token}").json()
    assert ctx["customer"] == {"name": "Jean Dupont", "email": "jean@example.com"}
    assert ctx["purchase"]["hours_purchased"] == 5
    assert ctx["purchase"]["hours_remaining"] == 5
    assert ctx["booking"] is None
    assert ctx["locale"] == "fr"

    [mail] = fakes["mailer"].sent
    assert mail["to"] == "jean@example.com"
    assert f"/fr/reservation/{token}" in mail["body"]


def test_checkout_exchange_is_idempotent(client, fakes):
    fakes["stripe"].add_session("cs_test_1")
    t1 = client.get("/api/checkout/cs_test_1").json()["token"]
    t2 = client.get("/api/checkout/cs_test_1").json()["token"]
    assert t1 == t2
    assert len(fakes["mailer"].sent) == 1


def test_webhook_then_redirect_single_purchase_and_replay_ignored(client, fakes):
    fakes["stripe"].add_session("cs_test_1")
    assert webhook(client, checkout_event("evt_1", "cs_test_1")).json() == {"status": "ok"}
    assert webhook(client, checkout_event("evt_1", "cs_test_1")).json() == {"status": "duplicate"}
    token = client.get("/api/checkout/cs_test_1").json()["token"]
    assert client.get(f"/api/booking/{token}").status_code == 200
    assert len(fakes["mailer"].sent) == 1

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import BookingToken, Purchase

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Purchase.id))) == 1
        assert db.scalar(select(func.count(BookingToken.id))) == 1


def test_webhook_rejects_bad_signature(client, fakes):
    fakes["stripe"].add_session("cs_test_1")
    assert webhook(client, checkout_event("evt_1", "cs_test_1"), signature="forged").status_code == 400


@pytest.mark.parametrize(
    "kwargs",
    [{"paid": False}, {"hours": None}],
    ids=["unpaid", "product-without-hours"],
)
def test_checkout_refused_when_not_eligible(client, fakes, kwargs):
    fakes["stripe"].add_session("cs_test_1", **kwargs)
    assert client.get("/api/checkout/cs_test_1").status_code == 404


def test_checkout_unknown_or_malformed(client):
    assert client.get("/api/checkout/cs_unknown").status_code == 404
    assert client.get("/api/checkout/pi_123").status_code == 404


def test_invalid_token(client):
    assert client.get("/api/booking/nope").status_code == 404
    assert client.get("/api/availability", params={"token": "nope"}).status_code == 404


# --- availability ---------------------------------------------------------------------


def test_availability_only_exposes_start_end(client, fakes, token_for):
    token = token_for()
    fakes["calendar"].busy["cal-formation"] = [(paris(2026, 10, 8, 10), paris(2026, 10, 8, 11))]
    r = client.get("/api/availability", params={"token": token})
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert slots and all(set(s) == {"start", "end"} for s in slots)
    starts = {s["start"] for s in slots}
    assert "2026-10-08T14:00:00+02:00" in starts
    # 10:00-11:00 busy + 15 min buffers -> 09:00, 10:00 and 11:00 gone.
    for hh in ("09", "10", "11"):
        assert f"2026-10-08T{hh}:00:00+02:00" not in starts
    assert "2026-10-08T12:00:00+02:00" in starts
    # Nothing before now + 24h, nothing on weekends.
    assert min(starts) >= "2026-10-06T08:00:00+02:00"
    assert not any(s.startswith("2026-10-10") or s.startswith("2026-10-11") for s in starts)
    # Calendar ids never leak.
    assert "cal-" not in r.text and "booking-cal" not in r.text


def test_availability_queries_enabled_sources_and_booking_calendar(client, fakes, token_for):
    token = token_for()
    client.get("/api/availability", params={"token": token})
    assert sorted(fakes["calendar"].freebusy_calls[-1]) == ["booking-cal", "cal-formation", "cal-principal"]


def test_availability_fails_closed_on_calendar_error(client, fakes, token_for):
    token = token_for()
    fakes["calendar"].errors.add("cal-principal")
    r = client.get("/api/availability", params={"token": token})
    assert r.status_code == 503


# --- booking ------------------------------------------------------------------------


def test_booking_end_to_end(client, fakes, token_for):
    token = token_for(hours=5)
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["start"] == "2026-10-08T14:00:00+02:00"
    assert body["end"] == "2026-10-08T15:00:00+02:00"
    assert (body["hours_purchased"], body["hours_booked"], body["hours_remaining"]) == (5, 1, 4)
    assert body["meet_url"].startswith("https://meet.google.com/")

    [event] = fakes["calendar"].events
    assert event["calendar_id"] == "booking-cal"
    assert event["summary"] == "Conseil IA - Jean Dupont"
    assert event["attendee_email"] == "jean@example.com"
    assert event["with_meet"] is True
    assert "Heures achetées : 5 h" in event["description"]
    assert "Heures restantes : 4 h" in event["description"]
    assert "pi_test_1" in event["description"]

    subjects = {m["subject"]: m for m in fakes["mailer"].sent}
    confirm = subjects["Votre rendez-vous Conseil IA est confirmé"]
    assert confirm["to"] == "jean@example.com"
    assert "Jeudi 8 octobre 2026" in confirm["body"]
    assert "14h00 - 15h00" in confirm["body"]
    assert "5 heures de conseil" in confirm["body"]
    assert "4 heures resteront à programmer" in confirm["body"]
    admin = subjects["NOUVELLE RÉSERVATION — Conseil IA"]
    assert admin["to"] == "admin@iafluence.test"
    assert "08/10/2026" in admin["body"] and "14:00 - 15:00" in admin["body"]

    ctx = client.get(f"/api/booking/{token}").json()
    assert ctx["booking"]["start"] == "2026-10-08T14:00:00+02:00"
    assert ctx["purchase"]["hours_remaining"] == 4
    assert client.get("/api/availability", params={"token": token}).json()["slots"] == []


def test_one_hour_purchase_leaves_zero(client, fakes, token_for):
    token = token_for(hours=1)
    body = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()}).json()
    assert body["hours_remaining"] == 0
    confirm = next(m for m in fakes["mailer"].sent if m["subject"].startswith("Votre rendez-vous"))
    assert "0 heures resteront" in confirm["body"]


def test_second_booking_same_purchase_refused(client, token_for):
    token = token_for()
    assert client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()}).status_code == 201
    r = client.post("/api/bookings", json={"token": token, "start": paris(2026, 10, 9, 10).isoformat()})
    assert r.status_code == 409
    assert r.json()["code"] == "already_booked"
    assert r.json()["booking"]["start"].startswith("2026-10-08T12:00:00")  # UTC


@pytest.mark.parametrize(
    "start",
    [
        paris(2026, 10, 8, 14, 30),  # misaligned
        paris(2026, 10, 8, 19),  # after hours
        paris(2026, 10, 5, 15),  # < 24h notice
        paris(2026, 10, 10, 10),  # Saturday
        paris(2026, 11, 20, 10),  # beyond 30 days
    ],
)
def test_booking_rejects_illegitimate_slots(client, token_for, start):
    token = token_for()
    r = client.post("/api/bookings", json={"token": token, "start": start.isoformat()})
    assert r.status_code == 422


def test_booking_rejects_naive_datetime(client, token_for):
    token = token_for()
    r = client.post("/api/bookings", json={"token": token, "start": "2026-10-08T14:00:00"})
    assert r.status_code == 422


def test_slot_taken_between_listing_and_confirmation(client, fakes, token_for):
    token = token_for()
    assert SLOT.isoformat() in [s["start"] for s in client.get("/api/availability", params={"token": token}).json()["slots"]]
    # Someone adds a meeting in a source calendar meanwhile (listing cache must be bypassed).
    fakes["calendar"].busy["cal-principal"] = [(paris(2026, 10, 8, 15), paris(2026, 10, 8, 16))]
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Ce créneau vient d’être réservé ou n’est plus disponible.")
    assert fakes["calendar"].events == []


def test_calendar_write_failure_keeps_hours(client, fakes, token_for):
    token = token_for()
    fakes["calendar"].fail_create = True
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert r.status_code == 502
    ctx = client.get(f"/api/booking/{token}").json()
    assert ctx["booking"] is None and ctx["purchase"]["hours_remaining"] == 5


def test_concurrent_bookings_same_slot_only_one_wins(client, fakes, token_for):
    from app.db import SessionLocal
    from app.services import booking_service

    t1 = token_for("cs_test_a", email="a@example.com", name="A")
    t2 = token_for("cs_test_b", email="b@outlook.fr", name="B")
    fakes["calendar"].create_delay = 0.3
    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(token):
        with SessionLocal() as db:
            barrier.wait()
            try:
                booking_service.book(db, fakes["calendar"], token, SLOT, NOW)
                results.append("ok")
            except booking_service.SlotTaken:
                results.append("taken")

    threads = [threading.Thread(target=attempt, args=(t,)) for t in (t1, t2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "taken"]
    assert len(fakes["calendar"].events) == 1


def test_db_constraint_prevents_overlap_even_without_lock(client, token_for):
    """Defence in depth: the exclusion constraint rejects overlapping confirmed bookings."""
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.models import Booking, Purchase

    token_for("cs_test_a", email="a@example.com")
    token_for("cs_test_b", email="b@example.com")
    with SessionLocal() as db:
        pa, pb = db.query(Purchase).order_by(Purchase.id).all()
        db.add(Booking(purchase_id=pa.id, customer_id=pa.customer_id, start_datetime=SLOT,
                       end_datetime=paris(2026, 10, 8, 15), status="confirmed"))
        db.commit()
        db.add(Booking(purchase_id=pb.id, customer_id=pb.customer_id, start_datetime=paris(2026, 10, 8, 14, 30),
                       end_datetime=paris(2026, 10, 8, 15, 30), status="confirmed"))
        with pytest.raises(IntegrityError):
            db.commit()


# --- refunds ------------------------------------------------------------------------


def test_full_refund_revokes_token_and_alerts_admin(client, fakes, token_for):
    token = token_for("cs_test_1")
    assert client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()}).status_code == 201
    event = {
        "id": "evt_refund",
        "type": "charge.refunded",
        "data": {"object": {"id": "ch_1", "payment_intent": "pi_test_1", "refunded": True}},
    }
    assert webhook(client, event).status_code == 200
    assert client.get(f"/api/booking/{token}").status_code == 404
    assert client.get("/api/checkout/cs_test_1").status_code == 404
    alert = next(m for m in fakes["mailer"].sent if m["subject"] == "REMBOURSEMENT — Conseil IA")
    assert "ATTENTION" in alert["body"] and "08/10/2026" in alert["body"]


def test_partial_refund_keeps_access(client, fakes, token_for):
    token = token_for("cs_test_1")
    event = {
        "id": "evt_refund",
        "type": "charge.refunded",
        "data": {"object": {"id": "ch_1", "payment_intent": "pi_test_1", "refunded": False}},
    }
    webhook(client, event)
    assert client.get(f"/api/booking/{token}").status_code == 200
    assert any("PARTIEL" in m["body"] for m in fakes["mailer"].sent)


# --- admin --------------------------------------------------------------------------


def test_admin_requires_login(client):
    assert client.get("/api/consultant/overview").status_code == 401
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401


def test_admin_overview(client, token_for):
    t5 = token_for("cs_test_5", hours=5, email="jean@example.com", name="Jean Dupont")
    token_for("cs_test_2", hours=2, email="marie@example.com", name="Marie Martin")
    client.post("/api/bookings", json={"token": t5, "start": SLOT.isoformat()})

    staff_login(client)
    data = client.get("/api/consultant/overview").json()
    k = data["kpis"]
    assert k["hours_sold"] == 7
    assert k["hours_booked"] == 1
    assert k["hours_to_schedule"] == 6
    assert k["hours_done"] == 0
    assert data["upcoming"][0]["customer"] == "Jean Dupont"
    clients = {c["name"]: c for c in data["clients"]}
    assert (clients["Jean Dupont"]["hours_purchased"], clients["Jean Dupont"]["hours_remaining"]) == (5, 4)
    assert clients["Marie Martin"]["booking"] is None
