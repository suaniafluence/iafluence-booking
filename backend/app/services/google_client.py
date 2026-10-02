"""Google API clients built from the stored OAuth refresh token of the IAfluence Gmail account."""

from functools import lru_cache

from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import HttpRequest, build_http

from app.config import get_config

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    # Drafts of the next-session email (no read access to the mailbox).
    "https://www.googleapis.com/auth/gmail.compose",
]


def credentials() -> Credentials:
    cfg = get_config()
    # No `scopes` on refresh: the token keeps whatever was consented, so a refresh token issued before a
    # scope was added to SCOPES keeps working (only the calls needing the new scope fail).
    return Credentials(
        token=None,
        refresh_token=cfg.google_refresh_token,
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )


def fresh_connection(http: AuthorizedHttp, *args, **kwargs) -> HttpRequest:
    """One HTTP connection per call, sharing the credentials (and their access token) of the cached client.

    Reusing the client's connection fails with BrokenPipeError once Google has closed it after a while idle:
    httplib2 does not reconnect on that error. It is not thread-safe either, and the clients are shared between
    the background jobs and the API requests."""
    return HttpRequest(AuthorizedHttp(http.credentials, http=build_http()), *args, **kwargs)


@lru_cache
def calendar_api():
    return build(
        "calendar", "v3", credentials=credentials(), requestBuilder=fresh_connection, cache_discovery=False
    )


@lru_cache
def gmail_api():
    return build("gmail", "v1", credentials=credentials(), requestBuilder=fresh_connection, cache_discovery=False)
