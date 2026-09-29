"""Google Calendar access.

Privacy rule (R05): the read path only ever uses `freebusy.query`, which returns busy
periods without any event detail. Event contents of existing calendars are never fetched.
"""

import threading
import time as _time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.services.availability import Interval


class CalendarUnavailable(Exception):
    """Free/busy could not be determined for at least one calendar — fail closed."""


class CalendarWriteError(Exception):
    pass


@dataclass(frozen=True)
class CreatedEvent:
    event_id: str
    meet_url: str | None


class CalendarGateway(Protocol):
    def free_busy(self, calendar_ids: list[str], time_min: datetime, time_max: datetime) -> list[Interval]: ...

    def create_event(
        self,
        calendar_id: str,
        *,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        timezone: str,
        attendee_email: str,
        attendee_name: str,
        with_meet: bool,
    ) -> CreatedEvent: ...

    def delete_event(self, calendar_id: str, event_id: str) -> None: ...


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class GoogleCalendarGateway:
    def __init__(self, api_factory=None):
        if api_factory is None:
            from app.services.google_client import calendar_api

            api_factory = calendar_api
        self._api = api_factory

    def free_busy(self, calendar_ids: list[str], time_min: datetime, time_max: datetime) -> list[Interval]:
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": cid} for cid in calendar_ids],
        }
        try:
            resp = self._api().freebusy().query(body=body).execute()
        except Exception as exc:  # network, auth, quota…
            raise CalendarUnavailable(str(exc)) from exc

        busy: list[Interval] = []
        for cid in calendar_ids:
            cal = resp.get("calendars", {}).get(cid)
            if cal is None or cal.get("errors"):
                reason = (cal or {}).get("errors", [{"reason": "missing"}])[0].get("reason")
                # Never leak calendar ids to clients; this message is only logged.
                raise CalendarUnavailable(f"free/busy error for a calendar source: {reason}")
            busy.extend(Interval(_parse(b["start"]), _parse(b["end"])) for b in cal.get("busy", []))
        return busy

    def create_event(
        self,
        calendar_id: str,
        *,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        timezone: str,
        attendee_email: str,
        attendee_name: str,
        with_meet: bool,
    ) -> CreatedEvent:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
            "attendees": [{"email": attendee_email, "displayName": attendee_name}],
            "transparency": "opaque",
            "reminders": {"useDefault": True},
        }
        if with_meet:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        try:
            ev = (
                self._api()
                .events()
                .insert(
                    calendarId=calendar_id,
                    body=body,
                    sendUpdates="all",  # Google emails the invitation to any address (R08)
                    conferenceDataVersion=1 if with_meet else 0,
                )
                .execute()
            )
        except Exception as exc:
            raise CalendarWriteError(str(exc)) from exc
        meet_url = ev.get("hangoutLink")
        if not meet_url:
            for ep in ev.get("conferenceData", {}).get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    meet_url = ep.get("uri")
                    break
        return CreatedEvent(event_id=ev["id"], meet_url=meet_url)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._api().events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="all").execute()


class CachedFreeBusy:
    """Short-lived cache for the availability listing. Booking always bypasses it."""

    def __init__(self, ttl_seconds: float = 60.0):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[tuple, tuple[float, list[Interval]]] = {}

    def get(self, gateway: CalendarGateway, ids: list[str], time_min: datetime, time_max: datetime):
        # Round to the minute so successive calls share an entry.
        key = (tuple(sorted(ids)), time_min.replace(second=0, microsecond=0), time_max.replace(second=0, microsecond=0))
        now = _time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit and now - hit[0] < self._ttl:
                return hit[1]
        busy = gateway.free_busy(ids, time_min, time_max)
        with self._lock:
            self._entries = {k: v for k, v in self._entries.items() if now - v[0] < self._ttl}
            self._entries[key] = (now, busy)
        return busy

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


freebusy_cache = CachedFreeBusy()
