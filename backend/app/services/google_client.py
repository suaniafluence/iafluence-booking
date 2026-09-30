"""Google API clients built from the stored OAuth refresh token of the IAfluence Gmail account."""

from functools import lru_cache

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

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


@lru_cache
def calendar_api():
    return build("calendar", "v3", credentials=credentials(), cache_discovery=False)


@lru_cache
def gmail_api():
    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)
