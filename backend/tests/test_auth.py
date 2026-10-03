"""Google sign-in of the staff, and the separate admin / consultant sessions (real PostgreSQL)."""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select, update

from app.config import get_config
from app.db import SessionLocal
from app.models import StaffUser
from app.services import google_sso
from tests.conftest import NOW, google_sign_in, staff_login

pytestmark = pytest.mark.usefixtures("db_clean")

ADMIN = "admin@iafluence.test"


def add_user(email, **roles):
    with SessionLocal() as db:
        db.add(StaffUser(email=email, name="", **({"is_consultant": True} | roles)))
        db.commit()


def user(email=ADMIN) -> StaffUser:
    with SessionLocal() as db:
        return db.scalar(select(StaffUser).where(StaffUser.email == email))


def start(client, role="consultant", **params):
    r = client.get("/api/auth/google/start", params={"role": role, **params}, follow_redirects=False)
    assert r.status_code == 302, r.text
    return r, parse_qs(urlparse(r.headers["location"]).query)["state"][0]


# --- the flow -----------------------------------------------------------------------------------------------------


def test_consultant_signs_in_with_google(client, fakes):
    r, state = start(client)
    assert r.headers["location"].startswith("https://accounts.google.test/")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("iaf_oauth=") and "SameSite=lax" in cookie and "Path=/api/auth" in cookie
    flow = fakes["sso"].flows[state]
    assert flow["redirect_uri"] == "https://booking.iafluence.test/api/auth/google/callback"
    assert len(flow["challenge"]) == 43  # S256 of the verifier, base64url without padding

    done = client.get(f"/api/auth/google/callback?code={ADMIN}|{state}&state={state}", follow_redirects=False)
    assert done.headers["location"] == "/consultant"
    session = [c for c in done.headers.get_list("set-cookie") if c.startswith("iaf_consultant=")][0]
    for attr in ("HttpOnly", "Max-Age=43200", "Path=/api;", "SameSite=strict"):
        assert attr in session
    assert client.get("/api/auth/me?role=consultant").json() == {"id": 1, "email": ADMIN, "name": "Suan Tay", "role": "consultant"}
    assert client.get("/api/consultant/me").status_code == 200
    stored = user()
    assert stored.google_sub == f"sub-{ADMIN}" and stored.last_login_at == NOW


def test_login_hint_is_passed_to_google(client, fakes):
    _, state = start(client, email="suan@iafluence.fr")
    assert fakes["sso"].flows[state]["hint"] == "suan@iafluence.fr"


def test_each_role_has_its_own_session(client):
    google_sign_in(client, "consultant")
    assert client.get("/api/admin/settings").status_code == 401
    assert google_sign_in(client, "admin").headers["location"] == "/admin"
    assert client.get("/api/admin/settings").status_code == 200
    client.post("/api/auth/logout?role=consultant")
    assert client.get("/api/consultant/me").status_code == 401
    assert client.get("/api/admin/settings").status_code == 200


def test_a_consultant_cannot_enter_the_admin_area(client):
    add_user("consultant@exemple.fr", is_admin=False)
    assert google_sign_in(client, "admin", "consultant@exemple.fr").headers["location"] == "/admin?erreur=non_autorise"
    assert google_sign_in(client, "consultant", "consultant@exemple.fr").headers["location"] == "/consultant"


@pytest.mark.parametrize(
    ("identity", "problem"),
    [
        ({"email_verified": False}, "email_non_verifie"),
        ({"email": ""}, "email_non_verifie"),
        ({"email": "inconnu@exemple.fr"}, "non_autorise"),
    ],
)
def test_refused_identities(client, fakes, identity, problem):
    fakes["sso"].identity = identity
    assert google_sign_in(client).headers["location"] == f"/consultant?erreur={problem}"
    assert client.get("/api/consultant/me").status_code == 401


def test_the_google_account_is_bound_at_the_first_sign_in(client, fakes):
    google_sign_in(client)
    client.post("/api/auth/logout?role=consultant")
    fakes["sso"].identity = {"sub": "someone-else"}
    assert google_sign_in(client).headers["location"] == "/consultant?erreur=compte_different"


def test_inactive_account_is_refused(client):
    with SessionLocal() as db:
        db.execute(update(StaffUser).values(active=False))
        db.commit()
    assert google_sign_in(client).headers["location"] == "/consultant?erreur=non_autorise"


def test_removing_a_role_ends_the_open_session(client):
    staff_login(client)
    assert client.get("/api/consultant/learners").status_code == 200
    with SessionLocal() as db:
        db.execute(update(StaffUser).values(is_consultant=False, is_admin=True))
        db.commit()
    r = client.get("/api/consultant/learners")
    assert r.status_code == 403 and r.json()["detail"] == "Accès retiré."


def test_state_must_match(client):
    _, state = start(client)
    r = client.get(f"/api/auth/google/callback?code={ADMIN}|{state}&state=autre", follow_redirects=False)
    assert r.headers["location"] == "/consultant?erreur=session_expiree"


def test_callback_without_the_flow_cookie(client):
    _, state = start(client)
    client.cookies.clear()
    r = client.get(f"/api/auth/google/callback?code={ADMIN}|{state}&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/consultant?erreur=session_expiree"


def test_forged_flow_cookie(client):
    forged = URLSafeTimedSerializer("attacker", salt="google-sign-in").dumps({"state": "s", "nonce": "n", "verifier": "v", "role": "admin"})
    client.cookies.set("iaf_oauth", forged, path="/api/auth")
    r = client.get("/api/auth/google/callback?code=x&state=s", follow_redirects=False)
    assert r.headers["location"] == "/consultant?erreur=session_expiree"


def test_cancelled_on_google(client):
    start(client, role="admin")
    r = client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.headers["location"] == "/admin?erreur=annule"
    assert 'iaf_oauth=""' in r.headers["set-cookie"]


def test_google_refuses_the_code(client, fakes):
    fakes["sso"].fail = True
    assert google_sign_in(client).headers["location"] == "/consultant?erreur=google"


def test_nonce_must_match(client, fakes):
    fakes["sso"].identity = {"nonce": "rejoue"}
    assert google_sign_in(client).headers["location"] == "/consultant?erreur=session_expiree"


def test_unknown_role(client):
    assert client.get("/api/auth/google/start?role=root", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/me?role=root").status_code == 404


def test_google_not_configured(client, monkeypatch):
    monkeypatch.setattr(get_config(), "google_sso_client_id", "")
    monkeypatch.setattr(get_config(), "google_client_id", "")
    assert client.get("/api/auth/methods").json() == {"google": False, "password": True}
    assert client.get("/api/auth/google/start?role=admin", follow_redirects=False).status_code == 404


def test_methods(client):
    assert client.get("/api/auth/methods").json() == {"google": True, "password": True}


def test_password_session_is_admin_only(client):
    assert client.post("/api/admin/login", json={"password": "test-password"}).status_code == 200
    assert client.get("/api/auth/me?role=admin").json()["id"] is None
    assert client.get("/api/consultant/me").status_code == 401


def test_a_cookie_of_one_role_is_refused_for_the_other(client):
    google_sign_in(client, "admin")
    admin_cookie = client.cookies.get("iaf_admin")
    client.cookies.set("iaf_consultant", admin_cookie, path="/api")
    assert client.get("/api/consultant/me").json()["detail"] == "Session expirée."


# --- google_sso, without the network ------------------------------------------------------------------------------


def test_authorization_url(monkeypatch):
    monkeypatch.setattr(get_config(), "google_sso_client_id", "cid")
    url = google_sso.LiveGoogleSso().authorization_url(
        redirect_uri="https://x/cb", state="st", nonce="no", code_challenge="ch", login_hint="a@b.fr"
    )
    params = parse_qs(urlparse(url).query)
    assert url.startswith(google_sso.AUTHORIZE_URL)
    assert params == {
        "client_id": ["cid"], "redirect_uri": ["https://x/cb"], "response_type": ["code"],
        "scope": ["openid email profile"], "state": ["st"], "nonce": ["no"], "code_challenge": ["ch"],
        "code_challenge_method": ["S256"], "prompt": ["select_account"], "login_hint": ["a@b.fr"],
    }


def test_pkce_pair():
    import base64
    import hashlib

    verifier, challenge = google_sso.new_pkce()
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_claims_from_another_issuer_are_refused():
    with pytest.raises(google_sso.SsoError):
        google_sso.identity_from_claims({"iss": "https://evil.example", "sub": "1"})
    identity = google_sso.identity_from_claims(
        {"iss": "accounts.google.com", "sub": 7, "email": "A@B.fr", "email_verified": "true", "nonce": "n"}
    )
    # Only a real boolean counts as verified.
    assert (identity.sub, identity.email, identity.email_verified) == ("7", "a@b.fr", False)


class TokenEndpoint:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error, self.sent = status, body or {"id_token": "jwt"}, error, None

    def __call__(self, url, data, timeout):
        if self.error:
            raise self.error
        self.sent = (url, data)
        return httpx.Response(self.status, json=self.body)


def test_exchange_checks_the_id_token(monkeypatch):
    from google.oauth2 import id_token

    endpoint = TokenEndpoint()
    monkeypatch.setattr(google_sso.httpx, "post", endpoint)
    monkeypatch.setattr(get_config(), "google_sso_client_id", "cid")
    monkeypatch.setattr(get_config(), "google_sso_client_secret", "secret")
    checked = []

    def verify(token, request, audience):
        checked.append((token, audience))
        return {"iss": "https://accounts.google.com", "sub": "42", "email": "s@i.fr", "email_verified": True, "nonce": "n"}

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    identity = google_sso.LiveGoogleSso().exchange(code="c", redirect_uri="https://x/cb", code_verifier="v")
    assert identity.sub == "42" and checked == [("jwt", "cid")]
    url, data = endpoint.sent
    assert url == google_sso.TOKEN_URL
    assert data == {
        "code": "c", "client_id": "cid", "client_secret": "secret", "redirect_uri": "https://x/cb",
        "grant_type": "authorization_code", "code_verifier": "v",
    }


@pytest.mark.parametrize(
    ("endpoint", "message"),
    [
        (TokenEndpoint(status=400), "code refusé"),
        (TokenEndpoint(body={"access_token": "x"}), "pas de jeton"),
        (TokenEndpoint(error=httpx.ConnectError("down")), "injoignable"),
    ],
)
def test_exchange_failures(monkeypatch, endpoint, message):
    monkeypatch.setattr(google_sso.httpx, "post", endpoint)
    with pytest.raises(google_sso.SsoError, match=message):
        google_sso.LiveGoogleSso().exchange(code="c", redirect_uri="r", code_verifier="v")


def test_invalid_id_token(monkeypatch):
    from google.oauth2 import id_token

    monkeypatch.setattr(google_sso.httpx, "post", TokenEndpoint())

    def invalid(*a, **kw):
        raise ValueError("bad signature")

    monkeypatch.setattr(id_token, "verify_oauth2_token", invalid)
    with pytest.raises(google_sso.SsoError, match="invalide"):
        google_sso.LiveGoogleSso().exchange(code="c", redirect_uri="r", code_verifier="v")
