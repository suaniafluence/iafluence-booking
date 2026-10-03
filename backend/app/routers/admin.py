"""Administration (/admin): configuration of the platform — Codex and Fireflies connections, staff accounts and
their roles, report and reminder settings. The day-to-day work is in the consultant cockpit (app.routers.consultant).

Google sign-in with the admin role (app.routers.auth), or the ADMIN_PASSWORD_HASH fallback below.
"""

import time
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth
from app.auth import require_admin
from app.config import get_config
from app.db import get_db
from app.deps import get_codex, get_fireflies, get_now
from app.models import CodexLogin, StaffUser
from app.schemas import FirefliesConnectIn, LoginIn, PlatformSettingsIn, StaffUserIn, StaffUserPatchIn
from app.services import codex_login, fireflies_account
from app.services.codex import CodexUnavailable
from app.services.fireflies import FirefliesError
from app.services.settings_service import get_settings

router = APIRouter(prefix="/api/admin")


@router.post("/login")
def login(body: LoginIn, response: Response):
    """Fallback when Google sign-in is unavailable: the admin area only."""
    cfg = get_config()
    try:
        ok = bool(cfg.admin_password_hash) and PasswordHasher().verify(cfg.admin_password_hash, body.password)
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok:
        time.sleep(1)  # slow down guessing
        raise HTTPException(401, "Mot de passe incorrect.")
    auth.open_session(response, "admin", None)
    return {"status": "ok"}


@router.post("/logout")
def logout(response: Response):
    auth.close_session(response, "admin")
    return {"status": "ok"}


# --- Codex connection (device authorization) -------------------------------------------------------------------


def _codex_call(action):
    try:
        return action()
    except CodexUnavailable as e:
        raise HTTPException(502, f"Le service Codex est injoignable : {e}")


def _login(db: Session, login_id: int) -> CodexLogin:
    login = db.scalar(select(CodexLogin).where(CodexLogin.id == login_id).with_for_update())
    if login is None:
        raise HTTPException(404, "Connexion introuvable.")
    return login


@router.get("/codex", dependencies=[Depends(require_admin)])
def codex_status(db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)):
    """connected / expired / disconnected / unavailable. Never any token: they stay in the codex container."""
    if not get_config().codex_enabled:
        return {"state": "not_configured", "email": None, "plan": None, "detail": None, "pending_login": None}
    return codex_login.status(db, codex, now)


@router.post("/codex/login", status_code=201, dependencies=[Depends(require_admin)])
def codex_start_login(db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)):
    """« Connecter Codex » : device code to type on https://auth.openai.com/codex/device."""
    return codex_login.login_dict(_codex_call(lambda: codex_login.start(db, codex, now)))


@router.get("/codex/login/{login_id}", dependencies=[Depends(require_admin)])
def codex_login_status(
    login_id: int, db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)
):
    return codex_login.login_dict(codex_login.refresh(db, codex, _login(db, login_id), now))


@router.post("/codex/login/{login_id}/cancel", dependencies=[Depends(require_admin)])
def codex_cancel_login(
    login_id: int, db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)
):
    return codex_login.login_dict(codex_login.cancel(db, codex, _login(db, login_id), now))


@router.post("/codex/logout", dependencies=[Depends(require_admin)])
def codex_logout(db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)):
    _codex_call(lambda: codex_login.logout(db, codex, now))
    return {"state": "disconnected"}


# --- Fireflies connection (API key) ----------------------------------------------------------------------------


@router.get("/fireflies", dependencies=[Depends(require_admin)])
def fireflies_status(db: Session = Depends(get_db)):
    """connected (admin | server) / disconnected. Never the key: only the Fireflies account it belongs to."""
    return fireflies_account.status(db)


@router.post("/fireflies", dependencies=[Depends(require_admin)])
def fireflies_connect(
    body: FirefliesConnectIn,
    db: Session = Depends(get_db),
    fireflies=Depends(get_fireflies),
    now: datetime = Depends(get_now),
):
    try:
        return fireflies_account.connect(db, fireflies, body.api_key, now)
    except FirefliesError as e:
        raise HTTPException(400, f"Fireflies a refusé la connexion : {e}.")


@router.delete("/fireflies", dependencies=[Depends(require_admin)])
def fireflies_disconnect(db: Session = Depends(get_db)):
    return fireflies_account.disconnect(db)


# --- platform settings -----------------------------------------------------------------------------------------


def _settings_dict(settings) -> dict:
    return {
        "send_without_review": settings.send_reports_without_review,
        "reminder_enabled": settings.reminder_enabled,
        "reminder_after_days": settings.reminder_after_days,
        "reminder_auto_send": settings.reminder_auto_send,
        "hide_after_days": settings.hide_after_days,
    }


@router.get("/settings", dependencies=[Depends(require_admin)])
def read_settings(db: Session = Depends(get_db)):
    return _settings_dict(get_settings(db))


@router.patch("/settings", dependencies=[Depends(require_admin)])
def update_settings(body: PlatformSettingsIn, db: Session = Depends(get_db)):
    """Inactivity reminders and the cockpit's « hidden after » delay."""
    settings = get_settings(db)
    values = body.model_dump(exclude_unset=True)
    after = values.get("reminder_after_days", settings.reminder_after_days)
    hide = values.get("hide_after_days", settings.hide_after_days)
    if hide <= after:
        raise HTTPException(422, "Le délai de masquage doit être plus long que celui de la relance.")
    for field, value in values.items():
        setattr(settings, field, value)
    db.commit()
    return _settings_dict(settings)


# --- staff accounts (Google sign-in) ----------------------------------------------------------------------------


def _user_dict(user: StaffUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
        "is_consultant": user.is_consultant,
        "active": user.active,
        "google_linked": user.google_sub is not None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    return {
        "users": [_user_dict(u) for u in db.scalars(select(StaffUser).order_by(StaffUser.id))],
        "google_enabled": get_config().sso_enabled,
    }


@router.post("/users", status_code=201, dependencies=[Depends(require_admin)])
def add_user(body: StaffUserIn, db: Session = Depends(get_db)):
    """Allow a Google address in the admin area, the cockpit, or both."""
    if not (body.is_admin or body.is_consultant):
        raise HTTPException(422, "Choisissez au moins un rôle.")
    user = StaffUser(email=str(body.email).lower(), name=body.name, is_admin=body.is_admin, is_consultant=body.is_consultant)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Cette adresse a déjà un compte.")
    return _user_dict(user)


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
def update_user(user_id: int, body: StaffUserPatchIn, db: Session = Depends(get_db)):
    """Roles, name, active flag; `unlink_google` lets the next sign-in bind another Google account."""
    user = db.scalar(select(StaffUser).where(StaffUser.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "Compte introuvable.")
    values = body.model_dump(exclude_unset=True)
    unlink = values.pop("unlink_google", False)
    for field, value in values.items():
        setattr(user, field, value)
    if not (user.is_admin or user.is_consultant):
        db.rollback()
        raise HTTPException(422, "Un compte garde au moins un rôle : désactivez-le plutôt.")
    if not (user.is_admin and user.active):
        others = db.scalar(
            select(func.count(StaffUser.id)).where(StaffUser.is_admin, StaffUser.active, StaffUser.id != user.id)
        )
        if others == 0 and not get_config().admin_password_hash:
            db.rollback()
            raise HTTPException(409, "Impossible : ce serait le dernier administrateur.")
    if unlink:
        user.google_sub = None
    db.commit()
    return _user_dict(user)
