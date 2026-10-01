"""Fireflies.ai GraphQL API: find the recording of a session and read its transcript.

Rate limits depend on the plan (Free 50 requests/day, Pro 500/day, Business 60/min): the pipeline lists the
transcripts of every waiting session in one request per poll, then reads the one it needs once.
Transcripts are returned to the caller only, never logged nor stored.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.config import get_config

log = logging.getLogger(__name__)

TIMEOUT_S = 30
# Enough for a few days of meetings; the window of a poll is at most a few hours wide.
LIST_LIMIT = 50

LIST_QUERY = """
query Transcripts($fromDate: DateTime, $toDate: DateTime, $limit: Int) {
  transcripts(fromDate: $fromDate, toDate: $toDate, limit: $limit) {
    id
    date
    meeting_link
    participants
    meeting_attendees { email }
  }
}
"""

SENTENCES_QUERY = """
query Transcript($id: String!) {
  transcript(id: $id) {
    id
    sentences { speaker_name text }
  }
}
"""


ACCOUNT_QUERY = """
query Account {
  user { email name }
}
"""


class FirefliesError(Exception):
    """Fireflies unreachable, key refused, quota reached or unexpected answer: try again at the next poll."""


@dataclass(frozen=True)
class TranscriptMeta:
    id: str
    start: datetime
    emails: frozenset[str] = field(default_factory=frozenset)
    meeting_link: str | None = None


@dataclass(frozen=True)
class FirefliesAccount:
    email: str | None
    name: str | None


@dataclass(frozen=True)
class Sentence:
    speaker: str
    text: str


class FirefliesGateway(Protocol):
    def list_transcripts(self, time_min: datetime, time_max: datetime) -> list[TranscriptMeta]: ...

    def sentences(self, transcript_id: str) -> list[Sentence]:
        """Empty while Fireflies is still processing the recording."""

    def account(self, api_key: str) -> FirefliesAccount:
        """Owner of this key (« Connexion Fireflies »): FirefliesError if the key is refused."""


def parse_meta(raw: dict) -> TranscriptMeta:
    emails = {e for e in raw.get("participants") or [] if e}
    emails |= {a["email"] for a in raw.get("meeting_attendees") or [] if a and a.get("email")}
    return TranscriptMeta(
        id=str(raw["id"]),
        # Fireflies dates are milliseconds since the epoch.
        start=datetime.fromtimestamp(float(raw["date"]) / 1000, UTC),
        emails=frozenset(e.strip().lower() for e in emails),
        meeting_link=raw.get("meeting_link") or None,
    )


def _server_key() -> str:
    return get_config().fireflies_api_key


class LiveFireflies:
    """api_key: read at each request, so a key connected from the admin applies without a restart."""

    def __init__(self, transport: httpx.BaseTransport | None = None, api_key: Callable[[], str] = _server_key):
        self._transport = transport
        self._api_key = api_key

    def _query(self, query: str, variables: dict, api_key: str | None = None) -> dict:
        key = api_key if api_key is not None else self._api_key()
        if not key:
            raise FirefliesError("Fireflies n'est pas connecté")
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_S) as http:
                r = http.post(
                    get_config().fireflies_api_url,
                    json={"query": query, "variables": variables},
                    headers={"Authorization": f"Bearer {key}"},
                )
        except httpx.HTTPError as e:
            raise FirefliesError(f"Fireflies injoignable ({type(e).__name__})") from e
        if r.status_code == 429:
            raise FirefliesError("quota de l'API Fireflies atteint")
        if r.status_code in (401, 403):
            raise FirefliesError("clé API Fireflies refusée")
        try:
            payload = r.json()
        except ValueError:
            payload = {}
        if r.status_code != 200 or payload.get("errors") or not isinstance(payload.get("data"), dict):
            codes = [err.get("code") or err.get("extensions", {}).get("code") for err in payload.get("errors") or []]
            raise FirefliesError(f"réponse Fireflies inattendue (HTTP {r.status_code}, {codes or 'sans détail'})")
        return payload["data"]

    def list_transcripts(self, time_min: datetime, time_max: datetime) -> list[TranscriptMeta]:
        data = self._query(
            LIST_QUERY,
            {
                "fromDate": time_min.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "toDate": time_max.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "limit": LIST_LIMIT,
            },
        )
        return [parse_meta(t) for t in data.get("transcripts") or [] if t and t.get("date") is not None]

    def sentences(self, transcript_id: str) -> list[Sentence]:
        transcript = self._query(SENTENCES_QUERY, {"id": transcript_id}).get("transcript")
        if transcript is None:
            raise FirefliesError("transcription Fireflies introuvable")
        return [
            Sentence(speaker=s.get("speaker_name") or "?", text=s["text"])
            for s in transcript.get("sentences") or []
            if s and s.get("text")
        ]


    def account(self, api_key: str) -> FirefliesAccount:
        user = self._query(ACCOUNT_QUERY, {}, api_key=api_key).get("user") or {}
        return FirefliesAccount(email=user.get("email") or None, name=user.get("name") or None)


def normalize_meet_url(url: str | None) -> str | None:
    """https://meet.google.com/abc-defg-hij?authuser=0 -> meet.google.com/abc-defg-hij"""
    if not url:
        return None
    url = url.strip().lower().split("?")[0].split("#")[0].rstrip("/")
    return url.removeprefix("https://").removeprefix("http://")
