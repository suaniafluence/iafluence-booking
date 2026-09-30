"""Admin: clients added by hand and the per-client auto-send choice (real PostgreSQL)."""

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import BookingToken, Customer, Purchase
from tests.conftest import ADMIN_PASSWORD, paris

pytestmark = pytest.mark.usefixtures("db_clean")

NEW = {"name": " Claire Durand ", "email": "Claire@Example.com", "hours": 4, "amount_cents": 48_000}


def login(client):
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200


def test_endpoints_require_the_admin_session(client):
    assert client.post("/api/admin/clients", json=NEW).status_code == 401
    assert client.patch("/api/admin/customers/1", json={"auto_send_next_link": True}).status_code == 401


def test_add_client_by_hand_creates_a_bookable_purchase_and_emails_the_link(client, fakes):
    login(client)
    r = client.post("/api/admin/clients", json=NEW)
    assert r.status_code == 201, r.text
    out = r.json()
    token = out["booking_url"].rsplit("/", 1)[1]
    assert out["booking_url"] == f"https://booking.iafluence.test/reservation/{token}"

    with SessionLocal() as db:
        purchase = db.get(Purchase, out["purchase_id"])
        assert (purchase.customer.name, purchase.customer.email) == ("Claire Durand", "claire@example.com")
        assert (purchase.product_id, purchase.product_name, purchase.amount_cents, purchase.currency) == (
            "manual", "Conseil IA", 48_000, "eur"
        )
        assert (purchase.hours_purchased, purchase.hours_booked, purchase.payment_status) == (4, 0, "paid")
        assert purchase.stripe_checkout_session_id.startswith("manual_") and purchase.stripe_payment_id is None
        assert db.scalar(select(BookingToken.token).where(BookingToken.purchase_id == purchase.id)) == token

    [mail] = fakes["mailer"].sent
    assert mail["to"] == "claire@example.com" and out["booking_url"] in mail["body"].splitlines()

    ctx = client.get(f"/api/booking/{token}").json()
    assert ctx["purchase"]["hours_remaining"] == 4
    booked = client.post("/api/bookings", json={"token": token, "start": paris(2026, 10, 8, 14).isoformat()})
    assert booked.status_code == 201

    client_row = client.get("/api/admin/overview").json()["clients"][0]
    assert client_row["manual"] is True and client_row["booking_url"] == out["booking_url"]
    assert client_row["auto_send_next_link"] is False


def test_add_client_without_email_and_existing_customer_is_reused(client, fakes, token_for):
    token_for(email="claire@example.com", name="Ancien Nom")
    fakes["mailer"].sent.clear()
    login(client)
    r = client.post("/api/admin/clients", json={**NEW, "product_name": "Atelier IA", "send_link": False})
    assert r.status_code == 201
    assert fakes["mailer"].sent == []
    with SessionLocal() as db:
        [customer] = db.scalars(select(Customer)).all()
        assert customer.name == "Claire Durand" and len(customer.purchases) == 2
        assert db.get(Purchase, r.json()["purchase_id"]).product_name == "Atelier IA"


@pytest.mark.parametrize(
    "bad",
    [{"name": ""}, {"email": "pas-un-email"}, {"hours": 0}, {"hours": 101}, {"amount_cents": -1}, {"product_name": ""}],
)
def test_add_client_validates_input(client, bad):
    login(client)
    assert client.post("/api/admin/clients", json={**NEW, **bad}).status_code == 422


def test_toggle_auto_send_per_client(client, token_for):
    token_for()
    login(client)
    [row] = client.get("/api/admin/overview").json()["clients"]
    assert row["auto_send_next_link"] is False and row["manual"] is False
    assert row["booking_url"].startswith("https://booking.iafluence.test/reservation/")

    r = client.patch(f"/api/admin/customers/{row['customer_id']}", json={"auto_send_next_link": True})
    assert r.json() == {"customer_id": row["customer_id"], "auto_send_next_link": True}
    assert client.get("/api/admin/overview").json()["clients"][0]["auto_send_next_link"] is True

    client.patch(f"/api/admin/customers/{row['customer_id']}", json={"auto_send_next_link": False})
    assert client.get("/api/admin/overview").json()["clients"][0]["auto_send_next_link"] is False


def test_toggle_unknown_customer(client):
    login(client)
    r = client.patch("/api/admin/customers/999", json={"auto_send_next_link": True})
    assert r.status_code == 404 and r.json()["detail"] == "Client introuvable."


def test_revoked_link_is_not_offered_to_the_admin(client, token_for):
    token_for()
    with SessionLocal() as db:
        for tok in db.scalars(select(BookingToken)):
            tok.revoked_at = paris(2026, 10, 1, 9)
        db.commit()
    login(client)
    assert client.get("/api/admin/overview").json()["clients"][0]["booking_url"] is None
