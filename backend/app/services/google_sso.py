"""Google sign-in of the staff (OpenID Connect, authorization code flow with PKCE).

The browser only carries the authorization code: the API exchanges it with Google over TLS, using the client
secret and the PKCE verifier, then checks the ID token (signature, audience, issuer, expiry) and its nonce.
Who may enter is decided by app.auth from the `staff_users` table, never by Google alone.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.config import get_config

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
TIMEOUT_S = 15


class SsoError(Exception):
    """Code refused by Google, invalid ID token, or Google unreachable."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str
    nonce: str | None


class SsoGateway(Protocol):
    def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str, login_hint: str | None) -> str: ...

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str) -> GoogleIdentity: ...


def new_pkce() -> tuple[str, str]:
    """(verifier, S256 challenge), RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def identity_from_claims(claims: dict) -> GoogleIdentity:
    if claims.get("iss") not in ISSUERS:
        raise SsoError("émetteur du jeton inattendu")
    return GoogleIdentity(
        sub=str(claims["sub"]),
        email=str(claims.get("email") or "").lower(),
        email_verified=claims.get("email_verified") is True,
        name=str(claims.get("name") or ""),
        nonce=claims.get("nonce"),
    )


class LiveGoogleSso:
    def authorization_url(self, *, redirect_uri, state, nonce, code_challenge, login_hint=None) -> str:
        params = {
            "client_id": get_config().sso_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def exchange(self, *, code, redirect_uri, code_verifier) -> GoogleIdentity:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        cfg = get_config()
        try:
            r = httpx.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cfg.sso_client_id,
                    "client_secret": cfg.sso_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                timeout=TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            raise SsoError(f"Google injoignable ({type(e).__name__})") from e
        if r.status_code != 200:
            raise SsoError(f"code refusé par Google ({r.status_code})")
        token = r.json().get("id_token")
        if not token:
            raise SsoError("pas de jeton d'identité")
        try:
            claims = id_token.verify_oauth2_token(token, Request(), audience=cfg.sso_client_id)
        except ValueError as e:
            raise SsoError("jeton d'identité invalide") from e
        return identity_from_claims(claims)
