"""GoogleCalendarGateway against a stubbed discovery client (no network)."""

from datetime import UTC, datetime

import pytest

from app.services.calendar_service import CalendarUnavailable, CalendarWriteError, GoogleCalendarGateway


class _Call:
    def __init__(self, result=None, exc=None, record=None, **kwargs):
        self._result, self._exc = result, exc
        if record is not None:
            record.append(kwargs)

    def execute(self):
        if self._exc:
            raise self._exc
        return self._result


class StubApi:
    def __init__(self, freebusy=None, insert=None, exc=None):
        self._freebusy, self._insert, self._exc = freebusy, insert, exc
        self.calls: list[dict] = []

    def freebusy(self):
        return self

    def query(self, body):
        return _Call(self._freebusy, self._exc, self.calls, body=body)

    def events(self):
        return self

    def insert(self, **kw):
        return _Call(self._insert, self._exc, self.calls, **kw)


T0 = datetime(2026, 10, 8, 7, tzinfo=UTC)
T1 = datetime(2026, 10, 8, 18, tzinfo=UTC)


def test_free_busy_merges_calendars_and_sends_only_ids():
    api = StubApi(
        freebusy={
            "calendars": {
                "a": {"busy": [{"start": "2026-10-08T08:00:00Z", "end": "2026-10-08T09:00:00Z"}]},
                "b": {"busy": [{"start": "2026-10-08T12:00:00+02:00", "end": "2026-10-08T13:00:00+02:00"}]},
            }
        }
    )
    busy = GoogleCalendarGateway(lambda: api).free_busy(["a", "b"], T0, T1)
    assert [(b.start.astimezone(UTC).hour, b.end.astimezone(UTC).hour) for b in busy] == [(8, 9), (10, 11)]
    assert api.calls[0]["body"]["items"] == [{"id": "a"}, {"id": "b"}]


@pytest.mark.parametrize(
    "resp",
    [
        {"calendars": {"a": {"busy": []}, "b": {"errors": [{"domain": "global", "reason": "notFound"}]}}},
        {"calendars": {"a": {"busy": []}}},
    ],
    ids=["calendar-error", "calendar-missing"],
)
def test_free_busy_fails_closed(resp):
    with pytest.raises(CalendarUnavailable):
        GoogleCalendarGateway(lambda: StubApi(freebusy=resp)).free_busy(["a", "b"], T0, T1)


def test_free_busy_network_error_fails_closed():
    with pytest.raises(CalendarUnavailable):
        GoogleCalendarGateway(lambda: StubApi(exc=OSError("boom"))).free_busy(["a"], T0, T1)


def test_create_event_with_meet_and_invitation():
    api = StubApi(insert={"id": "evt1", "hangoutLink": "https://meet.google.com/xxx-yyyy-zzz"})
    ev = GoogleCalendarGateway(lambda: api).create_event(
        "cal",
        summary="Conseil IA - Jean",
        description="d",
        start=T0,
        end=T1,
        timezone="Europe/Paris",
        attendee_email="jean@proton.me",
        attendee_name="Jean",
        with_meet=True,
    )
    assert ev.event_id == "evt1" and ev.meet_url == "https://meet.google.com/xxx-yyyy-zzz"
    call = api.calls[0]
    assert call["sendUpdates"] == "all"
    assert call["conferenceDataVersion"] == 1
    assert call["body"]["attendees"] == [{"email": "jean@proton.me", "displayName": "Jean"}]
    assert call["body"]["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}


def test_create_event_without_meet():
    api = StubApi(insert={"id": "evt1"})
    ev = GoogleCalendarGateway(lambda: api).create_event(
        "cal", summary="s", description="d", start=T0, end=T1, timezone="Europe/Paris",
        attendee_email="x@y.z", attendee_name="X", with_meet=False,
    )
    assert ev.meet_url is None
    assert "conferenceData" not in api.calls[0]["body"]
    assert api.calls[0]["conferenceDataVersion"] == 0


def test_create_event_error():
    with pytest.raises(CalendarWriteError):
        GoogleCalendarGateway(lambda: StubApi(exc=RuntimeError("403"))).create_event(
            "cal", summary="s", description="d", start=T0, end=T1, timezone="Europe/Paris",
            attendee_email="x@y.z", attendee_name="X", with_meet=True,
        )
