"""Admin: « Connexion Fireflies » (API key checked, stored encrypted, never sent back) (real PostgreSQL)."""

import httpx
import pytest

from app.config import get_config
from app.db import SessionLocal
from app.services import fireflies_account, session_reports
from app.services.fireflies import FirefliesError, LiveFireflies
from app.services.settings_service import get_settings
from tests.conftest import ADMIN_PASSWORD, NOW

pytestmark = pytest.mark.usefixtures("db_clean")

KEY = "ff-0123456789abcdef"
DISCONNECTED = {"state": "disconnected", "source": None, "email": None, "name": None, "detail": None}
CONNECTED = DISCONNECTED | {"state": "connected", "source": "admin", "email": "suan@iafluence.fr", "name": "Suan Tay"}


@pytest.fixture(autouse=True)
def codex_only(monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")
    monkeypatch.setattr(get_config(), "fireflies_api_key", "")


@pytest.fixture
def admin(client):
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200
    return client


def stored():
    with SessionLocal() as db:
        return get_settings(db).fireflies_api_key_enc


def reports_enabled():
    with SessionLocal() as db:
        return session_reports.enabled(db)


def test_connect_checks_the_key_and_stores_it_encrypted(admin, fakes):
    assert admin.get("/api/admin/fireflies").json() == DISCONNECTED
    assert admin.get("/api/admin/overview").json()["reports"]["enabled"] is False
    assert reports_enabled() is False

    r = admin.post("/api/admin/fireflies", json={"api_key": f"  {KEY}\n"})
    assert r.status_code == 200
    assert r.json() == CONNECTED
    assert fakes["fireflies"].checked_keys == [KEY]
    assert KEY not in r.text and KEY not in admin.get("/api/admin/fireflies").text
    assert stored() and KEY not in stored()
    assert fireflies_account.current_key() == KEY
    assert reports_enabled() is True
    assert admin.get("/api/admin/overview").json()["reports"]["enabled"] is True


def test_refused_key_keeps_the_current_connection(admin):
    admin.post("/api/admin/fireflies", json={"api_key": KEY})
    r = admin.post("/api/admin/fireflies", json={"api_key": "refusee"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Fireflies a refusé la connexion : clé API Fireflies refusée."
    assert fireflies_account.current_key() == KEY


@pytest.mark.parametrize("body", [{}, {"api_key": "   "}, {"api_key": "x" * 513}])
def test_invalid_key_input(admin, fakes, body):
    assert admin.post("/api/admin/fireflies", json=body).status_code == 422
    assert fakes["fireflies"].checked_keys == []


def test_disconnect_falls_back_to_the_server_key(admin, monkeypatch):
    admin.post("/api/admin/fireflies", json={"api_key": KEY})
    assert admin.delete("/api/admin/fireflies").json() == DISCONNECTED
    assert stored() is None
    assert reports_enabled() is False

    monkeypatch.setattr(get_config(), "fireflies_api_key", "server-key")
    assert admin.get("/api/admin/fireflies").json() == DISCONNECTED | {"state": "connected", "source": "server"}
    assert fireflies_account.current_key() == "server-key"
    assert reports_enabled() is True
    # A key connected from the admin takes precedence.
    admin.post("/api/admin/fireflies", json={"api_key": KEY})
    assert fireflies_account.current_key() == KEY


def test_reports_also_need_codex(admin, monkeypatch):
    admin.post("/api/admin/fireflies", json={"api_key": KEY})
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    assert reports_enabled() is False


def test_key_unreadable_after_a_session_secret_change(admin, fakes, monkeypatch):
    admin.post("/api/admin/fireflies", json={"api_key": KEY})
    # The admin session is signed with SESSION_SECRET too: checked on the service, as after a new login.
    monkeypatch.setattr(get_config(), "session_secret", "another-secret")
    with SessionLocal() as db:
        assert fireflies_account.status(db) == DISCONNECTED | {
            "detail": "La clé enregistrée n’est plus lisible (SESSION_SECRET a changé) : reconnectez Fireflies."
        }
        assert fireflies_account.current_key() == ""
        assert fireflies_account.connect(db, fakes["fireflies"], KEY, NOW) == CONNECTED


def test_fireflies_endpoints_need_the_admin(client):
    assert client.get("/api/admin/fireflies").status_code == 401
    assert client.post("/api/admin/fireflies", json={"api_key": KEY}).status_code == 401
    assert client.delete("/api/admin/fireflies").status_code == 401


def test_live_client_reads_the_key_at_each_request():
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(200, json={"data": {"user": {"email": "suan@iafluence.fr", "name": "Suan"}}})

    keys = iter(["first", "second"])
    live = LiveFireflies(transport=httpx.MockTransport(handler), api_key=lambda: next(keys))
    assert live.account("checked").email == "suan@iafluence.fr"
    live._query("query { x }", {})
    live._query("query { x }", {})
    assert seen == ["Bearer checked", "Bearer first", "Bearer second"]


def test_live_client_without_key_does_not_call_fireflies():
    def handler(request):
        raise AssertionError("no request without a key")

    with pytest.raises(FirefliesError, match="Fireflies n'est pas connecté"):
        LiveFireflies(transport=httpx.MockTransport(handler), api_key=lambda: "").sentences("ff_1")
