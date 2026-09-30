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


def test_free_busy_request_window_is_iso8601():
    api = StubApi(freebusy={"calendars": {"a": {}}})
    assert GoogleCalendarGateway(lambda: api).free_busy(["a"], T0, T1) == []
    assert api.calls[0]["body"]["timeMin"] == "2026-10-08T07:00:00+00:00"
    assert api.calls[0]["body"]["timeMax"] == "2026-10-08T18:00:00+00:00"


@pytest.mark.parametrize(
    "resp, reason",
    [
        ({"calendars": {"a": {"errors": [{"domain": "global", "reason": "notFound"}]}}}, "notFound"),
        ({"calendars": {}}, "missing"),
        ({}, "missing"),
    ],
)
def test_free_busy_error_reason_is_reported_without_calendar_id(resp, reason):
    with pytest.raises(CalendarUnavailable) as exc:
        GoogleCalendarGateway(lambda: StubApi(freebusy=resp)).free_busy(["a"], T0, T1)
    assert str(exc.value) == f"free/busy error for a calendar source: {reason}"


def _insert(api, with_meet=True):
    return GoogleCalendarGateway(lambda: api).create_event(
        "cal", summary="s", description="d", start=T0, end=T1, timezone="Europe/Paris",
        attendee_email="x@y.z", attendee_name="X", with_meet=with_meet,
    )


def test_create_event_body():
    api = StubApi(insert={"id": "evt1"})
    _insert(api, with_meet=True)
    call = api.calls[0]
    assert call["calendarId"] == "cal"
    body = call["body"]
    assert body["summary"] == "s" and body["description"] == "d"
    assert body["start"] == {"dateTime": "2026-10-08T07:00:00+00:00", "timeZone": "Europe/Paris"}
    assert body["end"] == {"dateTime": "2026-10-08T18:00:00+00:00", "timeZone": "Europe/Paris"}
    assert body["transparency"] == "opaque"
    assert body["reminders"] == {"useDefault": True}
    request_id = body["conferenceData"]["createRequest"]["requestId"]
    assert len(request_id) == 32
    api2 = StubApi(insert={"id": "evt2"})
    _insert(api2)
    assert api2.calls[0]["body"]["conferenceData"]["createRequest"]["requestId"] != request_id  # unique per event


def test_create_event_meet_url_from_video_entry_point():
    api = StubApi(
        insert={
            "id": "evt1",
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "phone", "uri": "tel:+33-1"},
                    {"entryPointType": "video", "uri": "https://meet.google.com/aaa-bbbb-ccc"},
                    {"entryPointType": "video", "uri": "https://meet.google.com/zzz"},
                ]
            },
        }
    )
    assert _insert(api).meet_url == "https://meet.google.com/aaa-bbbb-ccc"


def test_create_event_without_any_video_entry_point():
    api = StubApi(insert={"id": "evt1", "conferenceData": {"entryPoints": [{"entryPointType": "phone", "uri": "tel:1"}]}})
    assert _insert(api).meet_url is None


class _DeleteApi:
    def __init__(self):
        self.calls = []

    def events(self):
        return self

    def delete(self, **kw):
        self.calls.append(kw)
        return _Call({})


def test_delete_event_notifies_attendees():
    api = _DeleteApi()
    GoogleCalendarGateway(lambda: api).delete_event("cal", "evt1")
    assert api.calls == [{"calendarId": "cal", "eventId": "evt1", "sendUpdates": "all"}]


def test_default_api_factory_is_google_client():
    from app.services import google_client

    assert GoogleCalendarGateway()._api is google_client.calendar_api


# --- listing cache ------------------------------------------------------------------------


class _CountingGateway:
    def __init__(self):
        self.calls = 0

    def free_busy(self, ids, time_min, time_max):
        self.calls += 1
        return [f"result-{self.calls}"]


@pytest.fixture
def clock(monkeypatch):
    from app.services import calendar_service

    t = {"now": 1000.0}
    monkeypatch.setattr(calendar_service._time, "monotonic", lambda: t["now"])
    return t


def test_cache_hits_within_ttl_with_same_minute_and_any_id_order(clock):
    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(ttl_seconds=60), _CountingGateway()
    assert cache.get(gw, ["a", "b"], T0, T1) == ["result-1"]
    clock["now"] += 59
    assert cache.get(gw, ["b", "a"], T0.replace(second=30), T1.replace(second=59)) == ["result-1"]
    assert gw.calls == 1


def test_cache_expires_after_ttl_and_prunes_old_entries(clock):
    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(ttl_seconds=60), _CountingGateway()
    cache.get(gw, ["a"], T0, T1)
    cache.get(gw, ["other"], T0, T1)
    clock["now"] += 60
    assert cache.get(gw, ["a"], T0, T1) == ["result-3"]
    assert len(cache._entries) == 1  # the expired "other" entry was dropped


def test_cache_key_includes_range_and_ids(clock):
    from datetime import timedelta

    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(), _CountingGateway()
    cache.get(gw, ["a"], T0, T1)
    cache.get(gw, ["a"], T0 + timedelta(minutes=1), T1)
    cache.get(gw, ["a"], T0, T1 + timedelta(minutes=1))
    cache.get(gw, ["a", "b"], T0, T1)
    assert gw.calls == 4


def test_cache_clear(clock):
    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(), _CountingGateway()
    cache.get(gw, ["a"], T0, T1)
    cache.clear()
    cache.get(gw, ["a"], T0, T1)
    assert gw.calls == 2


def test_cache_does_not_store_failures(clock):
    from app.services.calendar_service import CachedFreeBusy

    class Failing:
        calls = 0

        def free_busy(self, *a):
            Failing.calls += 1
            raise CalendarUnavailable("down")

    cache = CachedFreeBusy()
    for _ in range(2):
        with pytest.raises(CalendarUnavailable):
            cache.get(Failing(), ["a"], T0, T1)
    assert Failing.calls == 2


def test_cache_rounds_keys_to_the_minute_including_microseconds(clock):
    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(), _CountingGateway()
    cache.get(gw, ["a"], T0.replace(microsecond=1), T1.replace(microsecond=2))
    cache.get(gw, ["a"], T0.replace(second=59, microsecond=999_999), T1.replace(microsecond=0))
    assert gw.calls == 1


def test_cache_forwards_the_exact_range():
    from app.services.calendar_service import CachedFreeBusy

    seen = []

    class Recording:
        def free_busy(self, ids, time_min, time_max):
            seen.append((ids, time_min, time_max))
            return []

    CachedFreeBusy().get(Recording(), ["a"], T0.replace(second=12), T1)
    assert seen == [(["a"], T0.replace(second=12), T1)]


def test_cache_keeps_fresh_entries_when_pruning(clock):
    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(ttl_seconds=60), _CountingGateway()
    cache.get(gw, ["a"], T0, T1)  # t=1000
    clock["now"] += 30
    cache.get(gw, ["b"], T0, T1)  # t=1030
    clock["now"] += 31
    cache.get(gw, ["a"], T0, T1)  # t=1061: "a" expired and refetched, "b" (31 s old) kept
    assert gw.calls == 3
    cache.get(gw, ["b"], T0, T1)
    assert gw.calls == 3


def test_cache_default_ttl_is_one_minute(clock):
    from app.services.calendar_service import CachedFreeBusy

    cache, gw = CachedFreeBusy(), _CountingGateway()
    cache.get(gw, ["a"], T0, T1)
    clock["now"] += 59.9
    cache.get(gw, ["a"], T0, T1)
    assert gw.calls == 1
    clock["now"] += 0.1
    cache.get(gw, ["a"], T0, T1)
    assert gw.calls == 2


def test_gateway_errors_keep_the_cause_for_the_logs():
    with pytest.raises(CalendarUnavailable, match="^boom$"):
        GoogleCalendarGateway(lambda: StubApi(exc=OSError("boom"))).free_busy(["a"], T0, T1)
    with pytest.raises(CalendarWriteError, match="^HttpError 403$"):
        _insert(StubApi(exc=RuntimeError("HttpError 403")))
