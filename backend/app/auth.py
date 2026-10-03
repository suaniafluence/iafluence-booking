"""Staff sessions: one per role, so the admin (configuration) and the consultant (cockpit) stay separate even for
the same email.

- Each role has its own signed cookie (HttpOnly, SameSite=Strict, 12 h). A Google session carries the staff user
  id: the user's role and `active` flag are read from the database on every request, so removing a role takes
  effect at once.
- The admin may also sign in with ADMIN_PASSWORD_HASH (fallback when Google is down); the cockpit is Google-only.
"""

from dataclasses import dataclass
from datetime import datetime

from fastapi import Cookie, Depends, HTTPException, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db
from app.models import StaffUser
from app.services.google_sso import GoogleIdentity

ROLES = ("admin", "consultant")
COOKIES = {"admin": "iaf_admin", "consultant": "iaf_consultant"}
SESSION_MAX_AGE = 12 * 3600
COOKIE_PATH = "/api"
# Path of the admin cookie before V3, cleared on logout.
LEGACY_ADMIN_PATH = "/api/admin"


class SignInRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Staff:
    """Who is signed in for this role. `id` is None for the admin password session."""

    id: int | None
    email: str
    name: str
    role: str


def _serializer(role: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().session_secret, salt=f"{role}-session")


def open_session(response: Response, role: str, user_id: int | None) -> None:
    payload = {"uid": user_id} if user_id is not None else {"pw": True}
    response.set_cookie(
        COOKIES[role],
        _serializer(role).dumps(payload),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=get_config().cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def close_session(response: Response, role: str) -> None:
    response.delete_cookie(COOKIES[role], path=COOKIE_PATH)
    if role == "admin":
        response.delete_cookie(COOKIES[role], path=LEGACY_ADMIN_PATH)


def session_staff(db: Session, role: str, cookie: str | None) -> Staff:
    if not cookie:
        raise HTTPException(401, "Authentification requise.")
    try:
        payload = _serializer(role).loads(cookie, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise HTTPException(401, "Session expirée.")
    uid = payload.get("uid") if isinstance(payload, dict) else None
    if uid is None:
        # Password session (pre-V3 cookies carried {"admin": true}).
        if role == "admin" and isinstance(payload, dict) and (payload.get("pw") or payload.get("admin")):
            return Staff(None, "", "Administrateur", role)
        raise HTTPException(401, "Session expirée.")
    user = db.get(StaffUser, uid)
    if user is None or not user.has_role(role):
        raise HTTPException(403, "Accès retiré.")
    return Staff(user.id, user.email, user.name, role)


def require_admin(iaf_admin: str | None = Cookie(None), db: Session = Depends(get_db)) -> Staff:
    return session_staff(db, "admin", iaf_admin)


def require_consultant(iaf_consultant: str | None = Cookie(None), db: Session = Depends(get_db)) -> Staff:
    return session_staff(db, "consultant", iaf_consultant)


def sign_in(db: Session, role: str, identity: GoogleIdentity, now: datetime) -> StaffUser:
    """The staff user for this Google identity, if it may hold `role`; SignInRefused(code) otherwise."""
    if not identity.email or not identity.email_verified:
        raise SignInRefused("email_non_verifie")
    user = db.scalar(select(StaffUser).where(StaffUser.email == identity.email).with_for_update())
    if user is None or not user.has_role(role):
        raise SignInRefused("non_autorise")
    if user.google_sub is None:
        user.google_sub = identity.sub
    elif user.google_sub != identity.sub:
        # Same address, another Google account (deleted and recreated, or a Workspace alias): refused.
        raise SignInRefused("compte_different")
    if not user.name and identity.name:
        user.name = identity.name
    user.last_login_at = now
    db.commit()
    return user


def default_consultant_id(db: Session) -> int | None:
    """Who follows a new customer while there is a single consultant."""
    return db.scalar(
        select(StaffUser.id).where(StaffUser.is_consultant, StaffUser.active).order_by(StaffUser.id).limit(1)
    )
