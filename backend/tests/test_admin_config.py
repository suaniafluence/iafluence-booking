"""Admin area: staff accounts and their roles, platform settings (real PostgreSQL)."""

import pytest
from sqlalchemy import select

from app.config import get_config
from app.db import SessionLocal
from app.models import Settings, StaffUser
from tests.conftest import ADMIN_PASSWORD, google_sign_in

pytestmark = pytest.mark.usefixtures("db_clean")


@pytest.fixture
def admin(client):
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200
    return client


def test_config_needs_the_admin_role(client):
    google_sign_in(client, "consultant")
    for method, path in [("get", "/api/admin/users"), ("get", "/api/admin/settings"), ("get", "/api/admin/codex")]:
        assert getattr(client, method)(path).status_code == 401


def test_list_users(admin):
    data = admin.get("/api/admin/users").json()
    assert data["google_enabled"] is True
    assert data["users"] == [
        {
            "id": 1, "email": "admin@iafluence.test", "name": "Suan Tay", "is_admin": True, "is_consultant": True,
            "active": True, "google_linked": False, "last_login_at": None,
        }
    ]


def test_add_a_consultant_who_then_signs_in(admin):
    r = admin.post("/api/admin/users", json={"email": "Claire@Exemple.fr", "name": "Claire"})
    assert r.status_code == 201
    assert (r.json()["email"], r.json()["is_consultant"], r.json()["is_admin"]) == ("claire@exemple.fr", True, False)
    assert google_sign_in(admin, "consultant", "claire@exemple.fr").headers["location"] == "/consultant"
    assert admin.post("/api/admin/users", json={"email": "claire@exemple.fr"}).status_code == 409


def test_a_user_needs_a_role(admin):
    r = admin.post("/api/admin/users", json={"email": "x@exemple.fr", "is_consultant": False})
    assert r.status_code == 422
    r = admin.patch("/api/admin/users/1", json={"is_admin": False, "is_consultant": False})
    assert r.status_code == 422


def test_update_roles_and_unlink_google(admin):
    google_sign_in(admin, "consultant")
    r = admin.patch("/api/admin/users/1", json={"is_consultant": False, "name": "Suan", "unlink_google": True})
    assert r.status_code == 200
    assert (r.json()["is_consultant"], r.json()["name"], r.json()["google_linked"]) == (False, "Suan", False)
    assert admin.get("/api/consultant/me").status_code == 403
    assert admin.patch("/api/admin/users/99", json={"active": False}).status_code == 404


def test_the_last_admin_stays_when_there_is_no_password(admin, monkeypatch):
    monkeypatch.setattr(get_config(), "admin_password_hash", "")
    r = admin.patch("/api/admin/users/1", json={"active": False})
    assert r.status_code == 409
    admin.post("/api/admin/users", json={"email": "autre@exemple.fr", "is_admin": True})
    assert admin.patch("/api/admin/users/1", json={"active": False}).status_code == 200


def test_with_the_password_fallback_the_last_admin_can_go(admin):
    assert admin.patch("/api/admin/users/1", json={"is_admin": False}).status_code == 200


def test_settings(admin):
    assert admin.get("/api/admin/settings").json() == {
        "send_without_review": False,
        "reminder_enabled": True,
        "reminder_after_days": 21,
        "reminder_auto_send": False,
        "hide_after_days": 60,
    }
    r = admin.patch("/api/admin/settings", json={"reminder_after_days": 30, "hide_after_days": 90, "reminder_auto_send": True})
    assert r.json()["reminder_after_days"] == 30 and r.json()["hide_after_days"] == 90
    with SessionLocal() as db:
        assert db.scalar(select(Settings.reminder_auto_send)) is True


@pytest.mark.parametrize(
    "body", [{"hide_after_days": 21}, {"reminder_after_days": 60}, {"reminder_after_days": 0}, {"hide_after_days": 1000}]
)
def test_invalid_settings(admin, body):
    assert admin.patch("/api/admin/settings", json=body).status_code == 422


def test_seed_does_not_duplicate_the_staff_account():
    from scripts.seed_settings import seed

    seed(admin_email="ADMIN@iafluence.test")
    with SessionLocal() as db:
        assert db.scalars(select(StaffUser.email)).all() == ["admin@iafluence.test"]
