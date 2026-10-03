"""Google sign-in of the admin and the consultants (see app.auth for the sessions and app.services.google_sso)."""

import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app import auth
from app.config import get_config
from app.db import get_db
from app.deps import get_now, get_sso
from app.services.google_sso import SsoError, new_pkce

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

FLOW_COOKIE = "iaf_oauth"
FLOW_PATH = "/api/auth"
FLOW_MAX_AGE = 10 * 60
# Where each role lands after signing in: fixed paths only, never taken from the request (no open redirect).
HOME = {"admin": "/admin", "consultant": "/consultant"}


def _flow_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().session_secret, salt="google-sign-in")


def redirect_uri() -> str:
    return f"{get_config().public_base_url.rstrip('/')}/api/auth/google/callback"


def _check_role(role: str) -> str:
    if role not in auth.ROLES:
        raise HTTPException(404, "Espace inconnu.")
    return role


@router.get("/methods")
def methods():
    cfg = get_config()
    return {"google": cfg.sso_enabled, "password": bool(cfg.admin_password_hash)}


@router.get("/google/start")
def google_start(role: str = Query(...), email: str | None = Query(None, max_length=320), sso=Depends(get_sso)):
    """Redirect to Google. state, nonce and the PKCE verifier stay in a signed cookie that lives 10 minutes."""
    _check_role(role)
    if not get_config().sso_enabled:
        raise HTTPException(404, "La connexion Google n'est pas configurée.")
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = new_pkce()
    url = sso.authorization_url(
        redirect_uri=redirect_uri(), state=state, nonce=nonce, code_challenge=challenge, login_hint=email or None
    )
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        FLOW_COOKIE,
        _flow_serializer().dumps({"state": state, "nonce": nonce, "verifier": verifier, "role": role}),
        max_age=FLOW_MAX_AGE,
        httponly=True,
        secure=get_config().cookie_secure,
        # Lax, not Strict: Google sends the browser back with a cross-site top-level redirect.
        samesite="lax",
        path=FLOW_PATH,
    )
    return response


@router.get("/google/callback")
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    iaf_oauth: str | None = Cookie(None),
    db: Session = Depends(get_db),
    sso=Depends(get_sso),
    now: datetime = Depends(get_now),
):
    flow = None
    if iaf_oauth:
        try:
            flow = _flow_serializer().loads(iaf_oauth, max_age=FLOW_MAX_AGE)
        except BadSignature:
            flow = None
    role = flow["role"] if flow and flow.get("role") in auth.ROLES else "consultant"

    def back(problem: str | None) -> RedirectResponse:
        target = HOME[role] if problem is None else f"{HOME[role]}?erreur={problem}"
        response = RedirectResponse(target, status_code=302)
        response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
        return response

    if flow is None:
        return back("session_expiree")
    if error or not code:
        return back("annule")
    if not state or not secrets.compare_digest(state, flow["state"]):
        return back("session_expiree")
    try:
        identity = sso.exchange(code=code, redirect_uri=redirect_uri(), code_verifier=flow["verifier"])
    except SsoError as e:
        log.warning("Google sign-in failed: %s", e)
        return back("google")
    if not identity.nonce or not secrets.compare_digest(identity.nonce, flow["nonce"]):
        return back("session_expiree")
    try:
        user = auth.sign_in(db, role, identity, now)
    except auth.SignInRefused as e:
        db.rollback()
        log.warning("Google sign-in refused for the %s area: %s", role, e.code)
        return back(e.code)
    response = back(None)
    auth.open_session(response, role, user.id)
    log.info("staff user %s signed in to the %s area", user.id, role)
    return response


@router.get("/me")
def me(
    role: str = Query(...),
    iaf_admin: str | None = Cookie(None),
    iaf_consultant: str | None = Cookie(None),
    db: Session = Depends(get_db),
):
    cookie = iaf_admin if _check_role(role) == "admin" else iaf_consultant
    staff = auth.session_staff(db, role, cookie)
    return {"id": staff.id, "email": staff.email, "name": staff.name, "role": staff.role}


@router.post("/logout")
def logout(response: Response, role: str = Query(...)):
    auth.close_session(response, _check_role(role))
    return {"status": "ok"}
