from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.availability import (
    Interval,
    SlotRules,
    available_slots,
    booking_window,
    busy_query_range,
    is_free,
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


# --- boundaries (each one pins a comparison operator) ---------------------------------


def test_intervals_touching_do_not_overlap():
    a = Interval(paris(2026, 10, 6, 9), paris(2026, 10, 6, 10))
    assert not a.overlaps(Interval(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11)))
    assert not Interval(paris(2026, 10, 6, 10), paris(2026, 10, 6, 11)).overlaps(a)
    assert a.overlaps(Interval(paris(2026, 10, 6, 9, 59), paris(2026, 10, 6, 11)))
    assert a.overlaps(Interval(paris(2026, 10, 6, 8), paris(2026, 10, 6, 9, 1)))
    assert a.overlaps(Interval(paris(2026, 10, 6, 9, 15), paris(2026, 10, 6, 9, 45)))


def test_busy_exactly_at_buffer_edge_keeps_slot():
    # 14:00-15:00 padded to 13:45-15:15.
    slot = Interval(paris(2026, 10, 6, 14), paris(2026, 10, 6, 15))
    assert is_free(slot, [Interval(paris(2026, 10, 6, 13), paris(2026, 10, 6, 13, 45))], RULES)
    assert is_free(slot, [Interval(paris(2026, 10, 6, 15, 15), paris(2026, 10, 6, 16))], RULES)
    assert not is_free(slot, [Interval(paris(2026, 10, 6, 13), paris(2026, 10, 6, 13, 46))], RULES)
    assert not is_free(slot, [Interval(paris(2026, 10, 6, 15, 14), paris(2026, 10, 6, 16))], RULES)


def test_asymmetric_buffers():
    rules = SlotRules(tz=PARIS, weekly=WEEKLY, buffer_before=timedelta(minutes=30), buffer_after=timedelta(0))
    slot = Interval(paris(2026, 10, 6, 14), paris(2026, 10, 6, 15))
    assert not is_free(slot, [Interval(paris(2026, 10, 6, 13), paris(2026, 10, 6, 13, 31))], rules)
    assert is_free(slot, [Interval(paris(2026, 10, 6, 13), paris(2026, 10, 6, 13, 30))], rules)
    assert is_free(slot, [Interval(paris(2026, 10, 6, 15), paris(2026, 10, 6, 16))], rules)
    w = booking_window(rules, NOW)
    assert busy_query_range(w, rules) == Interval(w.start - timedelta(minutes=30), w.end)


def test_booking_window_is_narrowed_never_widened():
    w = booking_window(RULES, NOW)
    assert w == Interval(NOW + timedelta(hours=24), NOW + timedelta(days=30))
    assert booking_window(RULES, NOW, frm=NOW, to=NOW + timedelta(days=90)) == w
    narrow = booking_window(RULES, NOW, frm=paris(2026, 10, 7, 0), to=paris(2026, 10, 8, 0))
    assert narrow == Interval(paris(2026, 10, 7, 0), paris(2026, 10, 8, 0))


def test_empty_or_inverted_window_returns_no_slot():
    assert available_slots(RULES, NOW, [], frm=paris(2026, 10, 8, 0), to=paris(2026, 10, 7, 0)) == []
    assert available_slots(RULES, NOW, [], frm=paris(2026, 10, 7, 9), to=paris(2026, 10, 7, 9)) == []


def test_slot_must_fit_entirely_in_window_and_rule():
    # Window 09:30 -> 11:00: 09:00 starts too early, 10:00-11:00 fits exactly.
    slots = available_slots(RULES, NOW, [], frm=paris(2026, 10, 7, 9, 30), to=paris(2026, 10, 7, 11))
    assert [s.start for s in slots] == [paris(2026, 10, 7, 10)]
    # A rule shorter than the duration yields nothing; one exactly as long yields one slot.
    assert available_slots(SlotRules(tz=PARIS, weekly={1: [(time(9), time(9, 59))]}), NOW, []) == []
    exact = available_slots(SlotRules(tz=PARIS, weekly={1: [(time(9), time(10))]}), NOW, [])
    assert local_starts(exact, TUESDAY) == ["09:00"]


def test_notice_boundary_is_inclusive():
    # now 08:00 Monday -> Tuesday 09:00 is 25 h away, Tuesday 08:00 would be exactly 24 h.
    rules = SlotRules(tz=PARIS, weekly={1: [(time(8), time(10))]})
    assert local_starts(available_slots(rules, NOW, []), TUESDAY) == ["08:00", "09:00"]
    assert resolve_slot(rules, NOW, paris(2026, 10, 6, 8)) is not None


def test_horizon_boundary_is_inclusive():
    # now + 30 days = Wednesday 4 November 08:00 (CET): a slot 07:00-08:00 ends exactly on the horizon.
    rules = SlotRules(tz=PARIS, weekly={2: [(time(7), time(9))]})
    starts = [s.start.astimezone(PARIS).strftime("%d %H:%M") for s in available_slots(rules, NOW, [])]
    assert starts[-1] == "04 07:00"
    assert resolve_slot(rules, NOW, paris(2026, 11, 4, 7)) is not None
    assert resolve_slot(rules, NOW, paris(2026, 11, 4, 8)) is None


def test_slots_are_sorted_across_rules_declared_out_of_order():
    rules = SlotRules(tz=PARIS, weekly={1: [(time(14), time(16)), (time(9), time(11))]})
    assert local_starts(available_slots(rules, NOW, []), TUESDAY) == ["09:00", "10:00", "14:00", "15:00"]


def test_duration_differs_from_step():
    rules = SlotRules(tz=PARIS, weekly={1: [(time(9), time(11))]}, duration=timedelta(minutes=90), step=timedelta(minutes=30))
    slots = [s for s in available_slots(rules, NOW, []) if s.start.astimezone(PARIS).date() == TUESDAY]
    assert [(s.start.astimezone(PARIS).strftime("%H:%M"), (s.end - s.start)) for s in slots] == [
        ("09:00", timedelta(minutes=90)),
        ("09:30", timedelta(minutes=90)),
    ]


def test_dst_spring_forward_keeps_local_wall_clock():
    # 29 March 2026: CET -> CEST. Monday 30 March 09:00 local is 07:00 UTC.
    now = paris(2026, 3, 27, 8)
    slots = available_slots(RULES, now, [])
    monday = [s for s in slots if s.start.astimezone(PARIS).date() == datetime(2026, 3, 30).date()]
    assert monday[0].start == datetime(2026, 3, 30, 7, tzinfo=UTC)
    assert all(s.end - s.start == timedelta(hours=1) for s in monday)


def test_resolve_slot_needs_exact_start_and_returns_rule_duration():
    rules = SlotRules(tz=PARIS, weekly={1: [(time(9), time(12))]}, duration=timedelta(minutes=45), step=timedelta(minutes=60))
    assert resolve_slot(rules, NOW, paris(2026, 10, 6, 10)) == Interval(paris(2026, 10, 6, 10), paris(2026, 10, 6, 10, 45))
    assert resolve_slot(rules, NOW, paris(2026, 10, 6, 10, 0) + timedelta(seconds=1)) is None
    # Far outside the window: the narrowed day window is empty.
    assert resolve_slot(rules, NOW, paris(2027, 6, 1, 10)) is None
    assert resolve_slot(rules, NOW, paris(2025, 6, 3, 10)) is None
