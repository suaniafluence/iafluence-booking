"""Pure slot engine: turns weekly rules + busy intervals into bookable slots.

No I/O here. Everything is timezone-aware; slots are generated in the configured
local timezone (DST-safe) and compared in UTC.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, order=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class SlotRules:
    tz: ZoneInfo
    # weekday (0 = Monday) -> list of (start, end) local wall-clock intervals
    weekly: Mapping[int, Sequence[tuple[time, time]]] = field(default_factory=dict)
    duration: timedelta = timedelta(minutes=60)
    step: timedelta = timedelta(minutes=60)
    min_notice: timedelta = timedelta(hours=24)
    max_window: timedelta = timedelta(days=30)
    buffer_before: timedelta = timedelta(minutes=15)
    buffer_after: timedelta = timedelta(minutes=15)


def booking_window(
    rules: SlotRules, now: datetime, frm: datetime | None = None, to: datetime | None = None
) -> Interval:
    """The period in which a slot may start/end: [now + notice, now + horizon], narrowed by from/to."""
    start = now + rules.min_notice
    end = now + rules.max_window
    if frm is not None:
        start = max(start, frm)
    if to is not None:
        end = min(end, to)
    return Interval(start, end)


def busy_query_range(window: Interval, rules: SlotRules) -> Interval:
    """Range that must be sent to free/busy so buffers at the edges are honoured."""
    return Interval(window.start - rules.buffer_before, window.end + rules.buffer_after)


def _local_days(window: Interval, tz: ZoneInfo) -> Iterable[date]:
    day = window.start.astimezone(tz).date()
    last = window.end.astimezone(tz).date()
    while day <= last:
        yield day
        day += timedelta(days=1)


def candidate_slots(rules: SlotRules, window: Interval) -> list[Interval]:
    """All rule-aligned slots fully contained in the window (ignores busy periods)."""
    slots: list[Interval] = []
    for day in _local_days(window, rules.tz):
        for rule_start, rule_end in rules.weekly.get(day.weekday(), ()):
            # Local wall-clock -> UTC, so DST days are handled by zoneinfo.
            cursor = datetime.combine(day, rule_start, tzinfo=rules.tz).astimezone(UTC)
            limit = datetime.combine(day, rule_end, tzinfo=rules.tz).astimezone(UTC)
            while cursor + rules.duration <= limit:
                slot = Interval(cursor, cursor + rules.duration)
                if slot.start >= window.start and slot.end <= window.end:
                    slots.append(slot)
                cursor += rules.step
    slots.sort()
    return slots


def is_free(slot: Interval, busy: Iterable[Interval], rules: SlotRules) -> bool:
    """A slot is free when no busy period touches it once buffers are applied."""
    padded = Interval(slot.start - rules.buffer_before, slot.end + rules.buffer_after)
    return not any(padded.overlaps(b) for b in busy)


def available_slots(
    rules: SlotRules,
    now: datetime,
    busy: Sequence[Interval],
    frm: datetime | None = None,
    to: datetime | None = None,
) -> list[Interval]:
    window = booking_window(rules, now, frm, to)
    if window.start >= window.end:
        return []
    return [s for s in candidate_slots(rules, window) if is_free(s, busy, rules)]


def resolve_slot(rules: SlotRules, now: datetime, start: datetime) -> Interval | None:
    """Return the slot starting exactly at `start` if it is a legitimate, in-window slot."""
    if start.tzinfo is None:
        return None
    window = booking_window(rules, now)
    day_window = Interval(
        max(window.start, start - timedelta(days=1)), min(window.end, start + timedelta(days=1))
    )
    if day_window.start >= day_window.end:
        return None
    for slot in candidate_slots(rules, day_window):
        if slot.start == start:
            return slot
    return None
