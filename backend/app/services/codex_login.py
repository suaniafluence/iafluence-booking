"""« Connexion Codex » in the admin: device authorization of the codex app-server with the ChatGPT plan.

PENDING -> COMPLETED | EXPIRED | DENIED | CANCELLED | ERROR. The app-server reports the outcome on the connection
that started the login; the admin page also polls every few seconds, and each poll asks the app-server whether an
account is now connected, so a lost connection or an API restart never leaves a login stuck.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CodexLogin
from app.services.codex import DEVICE_CODE_TTL_S, CodexGateway, CodexUnavailable

log = logging.getLogger(__name__)

TERMINAL = ("COMPLETED", "EXPIRED", "DENIED", "CANCELLED", "ERROR")


def _close(login: CodexLogin, status: str, now: datetime, error: str | None = None) -> None:
    login.status, login.error = status, error
    login.user_code = ""  # one-time code: useless once the login is over
    if status == "COMPLETED":
        login.completed_at = now


def finish(login_id: str, status: str, error: str | None) -> None:
    """Outcome reported by the app-server (called from the watcher thread of LiveCodex)."""
    with SessionLocal() as db:
        login = db.scalar(
            select(CodexLogin).where(CodexLogin.login_id == login_id, CodexLogin.status == "PENDING").with_for_update()
        )
        if login is not None:
            _close(login, status, datetime.now(UTC), error)
            db.commit()


def start(db: Session, codex: CodexGateway, now: datetime) -> CodexLogin:
    """A new « Connecter Codex » replaces the login still pending, if any."""
    for pending in db.scalars(select(CodexLogin).where(CodexLogin.status == "PENDING").with_for_update()):
        cancel(db, codex, pending, now)
    code = codex.start_login(finish)
    login = CodexLogin(
        login_id=code.login_id,
        verification_url=code.verification_url,
        user_code=code.user_code,
        status="PENDING",
        expires_at=now + timedelta(seconds=DEVICE_CODE_TTL_S),
    )
    db.add(login)
    db.commit()
    return login


def refresh(db: Session, codex: CodexGateway, login: CodexLogin, now: datetime) -> CodexLogin:
    """Status check of a pending login (the admin page polls it every 3 s)."""
    if login.status != "PENDING":
        return login
    if now >= login.expires_at:
        _close(login, "EXPIRED", now)
    else:
        try:
            if codex.account() is not None:
                _close(login, "COMPLETED", now)
        except CodexUnavailable as e:
            log.warning("codex status check failed: %s", e)
    db.commit()
    return login


def cancel(db: Session, codex: CodexGateway, login: CodexLogin, now: datetime) -> CodexLogin:
    if login.status == "PENDING":
        try:
            codex.cancel_login(login.login_id)
        except CodexUnavailable as e:
            log.warning("codex login cancel failed: %s", e)
        _close(login, "CANCELLED", now)
        db.commit()
    return login


def logout(db: Session, codex: CodexGateway, now: datetime) -> None:
    codex.logout()
    db.execute(
        update(CodexLogin)
        .where(CodexLogin.status == "COMPLETED", CodexLogin.ended_at.is_(None))
        .values(ended_at=now)
    )
    db.commit()


def login_dict(login: CodexLogin) -> dict:
    pending = login.status == "PENDING"
    return {
        "id": login.id,
        "status": login.status,
        "verification_url": login.verification_url if pending else None,
        "user_code": login.user_code if pending else None,
        "expires_at": login.expires_at.astimezone(UTC).isoformat(),
        "error": login.error,
    }


def status(db: Session, codex: CodexGateway, now: datetime) -> dict:
    """connected | expired (was connected, the ChatGPT session ended) | disconnected | unavailable."""
    pending = db.scalar(
        select(CodexLogin)
        .where(CodexLogin.status == "PENDING", CodexLogin.expires_at > now)
        .order_by(CodexLogin.id.desc())
    )
    out = {"state": "disconnected", "email": None, "plan": None, "detail": None}
    out["pending_login"] = login_dict(pending) if pending else None
    try:
        account = codex.account()
    except CodexUnavailable as e:
        return out | {"state": "unavailable", "detail": str(e)}
    if account is not None:
        return out | {"state": "connected", "email": account.email, "plan": account.plan}
    session = db.scalar(
        select(CodexLogin).where(CodexLogin.status == "COMPLETED").order_by(CodexLogin.completed_at.desc())
    )
    if session is not None and session.ended_at is None:
        out["state"] = "expired"
    return out
