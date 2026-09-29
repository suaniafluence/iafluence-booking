from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.availability import (
    Interval,
    SlotRules,
    available_slots,
    booking_window,
    busy_query_range,
    resolve_slot,
)

PARIS = ZoneInfo("Europe/Paris")
WEEKLY = {
    0: [(time(9), time(18))],
    1: [(time(9), time(18))],
    2: [(time(9), time(18))],
    3: [(time(9), time(18))],
    4: [(time(9), time(17))],
}
RULES = SlotRules(tz=PARIS, weekly=WEEKLY)


def paris(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=PARIS)


def local_starts(slots, day):
    return [s.start.astimezone(PARIS).strftime("%H:%M") for s in slots if s.start.astimezone(PARIS).date() == day]


# Monday 5 Oct 2026, 08:00 — so Tuesday 6 Oct 08:00 is the earliest possible start.
NOW = paris(2026, 10, 5, 8)
TUESDAY = datetime(2026, 10, 6).date()


def test_full_free_day_has_hourly_slots():
    slots = available_slots(RULES, NOW, busy=[])
    assert local_starts(slots, TUESDAY) == [f"{h:02d}:00" for h in range(9, 18)]


def test_friday_ends_at_17_and_weekend_is_closed():
    slots = available_slots(RULES, NOW, busy=[])
    fri = datetime(2026, 10, 9).date()
    assert local_starts(slots, fri)[-1] == "16:00"
    assert local_starts(slots, datetime(2026, 10, 10).date()) == []
    assert local_starts(slots, datetime(2026, 10, 11).date()) == []


def test_buffer_example_from_spec():
    # Existing 10:00-11:00 blocks 09:45-11:15 -> 09:00 (ends 10:00 + 15 buffer) and 11:00 are blocked.
    busy = [Interval(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11))]
    starts = local_starts(available_slots(RULES, NOW, busy), TUESDAY)
    assert "09:00" not in starts
    assert "10:00" not in starts
    assert "11:00" not in starts
    assert starts[0] == "12:00"


def test_no_buffer_allows_adjacent_slots():
    rules = SlotRules(tz=PARIS, weekly=WEEKLY, buffer_before=timedelta(0), buffer_after=timedelta(0))
    busy = [Interval(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11))]
    starts = local_starts(available_slots(rules, NOW, busy), TUESDAY)
    assert "09:00" in starts and "11:00" in starts and "10:00" not in starts


def test_minimum_notice_24h():
    # Monday 14:00 -> nothing before Tuesday 14:00.
    now = paris(2026, 10, 5, 14)
    slots = available_slots(RULES, now, busy=[])
    assert local_starts(slots, datetime(2026, 10, 5).date()) == []
    assert local_starts(slots, TUESDAY)[0] == "14:00"


def test_horizon_30_days():
    slots = available_slots(RULES, NOW, busy=[])
    assert max(s.end for s in slots) <= NOW + timedelta(days=30)
    assert min(s.start for s in slots) >= NOW + timedelta(hours=24)


def test_from_to_narrow_the_window():
    slots = available_slots(RULES, NOW, [], frm=paris(2026, 10, 7, 0), to=paris(2026, 10, 8, 0))
    days = {s.start.astimezone(PARIS).date() for s in slots}
    assert days == {datetime(2026, 10, 7).date()}


def test_multiple_intervals_per_day_lunch_break():
    rules = SlotRules(tz=PARIS, weekly={1: [(time(9), time(12)), (time(14), time(18))]})
    assert local_starts(available_slots(rules, NOW, []), TUESDAY) == [
        "09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"
    ]


def test_dst_change_last_sunday_of_october():
    # 25 Oct 2026: CEST -> CET. Monday 26 Oct slots must still be 09:00 local, offset +01:00.
    now = paris(2026, 10, 23, 8)
    slots = available_slots(RULES, now, [])
    monday = [s for s in slots if s.start.astimezone(PARIS).date() == datetime(2026, 10, 26).date()]
    assert monday[0].start.astimezone(PARIS).strftime("%H:%M %z") == "09:00 +0100"
    assert monday[0].start == datetime(2026, 10, 26, 8, tzinfo=UTC)
    friday_before = [s for s in slots if s.start.astimezone(PARIS).date() == datetime(2026, 10, 23).date()]
    assert friday_before == []  # notice


def test_half_hour_step():
    rules = SlotRules(tz=PARIS, weekly={1: [(time(9), time(11))]}, step=timedelta(minutes=30))
    assert local_starts(available_slots(rules, NOW, []), TUESDAY) == ["09:00", "09:30", "10:00"]


def test_resolve_slot_accepts_only_legit_starts():
    assert resolve_slot(RULES, NOW, paris(2026, 10, 6, 14)) == Interval(
        paris(2026, 10, 6, 14), paris(2026, 10, 6, 15)
    )
    assert resolve_slot(RULES, NOW, paris(2026, 10, 6, 14, 30)) is None  # misaligned
    assert resolve_slot(RULES, NOW, paris(2026, 10, 6, 18)) is None  # outside hours
    assert resolve_slot(RULES, NOW, paris(2026, 10, 5, 15)) is None  # notice
    assert resolve_slot(RULES, NOW, paris(2026, 11, 10, 10)) is None  # horizon
    assert resolve_slot(RULES, NOW, paris(2026, 10, 10, 10)) is None  # Saturday
    assert resolve_slot(RULES, NOW, datetime(2026, 10, 6, 14)) is None  # naive


def test_resolve_slot_matches_equivalent_utc_instant():
    assert resolve_slot(RULES, NOW, datetime(2026, 10, 6, 12, tzinfo=UTC)) is not None  # 14:00 Paris


def test_busy_query_range_includes_buffers():
    w = booking_window(RULES, NOW)
    r = busy_query_range(w, RULES)
    assert r.start == w.start - timedelta(minutes=15)
    assert r.end == w.end + timedelta(minutes=15)
