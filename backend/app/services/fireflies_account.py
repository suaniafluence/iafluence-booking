"""« Connexion Fireflies » in the admin: the API key that lets the session reports read the transcripts.

Fireflies has no OAuth for this API: the admin pastes the key of their account (Settings > Developer settings).
It is checked against Fireflies, then stored encrypted (Fernet, key derived from SESSION_SECRET) and never sent
back to the browser. Without a key connected here, FIREFLIES_API_KEY of the server applies.
"""

import base64
import hashlib
import logging
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import SessionLocal
from app.services.fireflies import FirefliesGateway
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"iafluence-fireflies-key:" + get_config().session_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _stored_key(db: Session) -> str | None:
    """None: nothing stored, or unreadable because SESSION_SECRET changed (reconnect from the admin)."""
    encrypted = get_settings(db).fireflies_api_key_enc
    if not encrypted:
        return None
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        log.warning("stored Fireflies key unreadable (SESSION_SECRET changed?): reconnect Fireflies in the admin")
        return None


def api_key(db: Session) -> str:
    return _stored_key(db) or get_config().fireflies_api_key


def current_key() -> str:
    """Resolver of LiveFireflies: read at each request."""
    with SessionLocal() as db:
        return api_key(db)


def status(db: Session) -> dict:
    """connected (source admin | server) | disconnected. Never the key itself."""
    s = get_settings(db)
    out = {"state": "disconnected", "source": None, "email": None, "name": None, "detail": None}
    if _stored_key(db):
        return out | {"state": "connected", "source": "admin", "email": s.fireflies_email, "name": s.fireflies_name}
    if get_config().fireflies_api_key:
        return out | {"state": "connected", "source": "server"}
    if s.fireflies_api_key_enc:
        out["detail"] = "La clé enregistrée n’est plus lisible (SESSION_SECRET a changé) : reconnectez Fireflies."
    return out


def connect(db: Session, fireflies: FirefliesGateway, key: str, now: datetime) -> dict:
    """Checked first: FirefliesError (key refused, Fireflies unreachable) leaves the current connection as is."""
    account = fireflies.account(key)
    s = get_settings(db)
    s.fireflies_api_key_enc = _fernet().encrypt(key.encode()).decode()
    s.fireflies_email, s.fireflies_name, s.fireflies_connected_at = account.email, account.name, now
    db.commit()
    return status(db)


def disconnect(db: Session) -> dict:
    s = get_settings(db)
    s.fireflies_api_key_enc = s.fireflies_email = s.fireflies_name = s.fireflies_connected_at = None
    db.commit()
    return status(db)
