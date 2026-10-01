"""Printable calendar for the admin: every busy period of all the calendars, one A4 page per week.

Nothing about the events is printed: each period says « Occupé ». A period whose events all end
with « ? » in Google Calendar (not fixed yet, not sure) is drawn with a dotted border. Printed
very light to spare ink.
"""

import io
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas

from app.services.availability import Interval
from app.services.calendar_service import BusyEvent, CalendarGateway, CalendarUnavailable
from app.services.formatting import MONTHS, WEEKDAYS

log = logging.getLogger(__name__)

MAX_DAYS = 366  # a whole year, leap years included: 53 pages at most
FREE_BUSY_SPAN = timedelta(days=31)  # Google refuses free/busy over long ranges: asked month by month
DEFAULT_HOURS = (8, 20)  # grid shown at least from 08:00 to 20:00, longer when a period falls outside

JOURS, MOIS = WEEKDAYS["fr"], MONTHS["fr"]  # the admin is in French

BUSY = "Occupé"
LEGEND_TENTATIVE = "Pas encore fixé ou pas sûr"


@dataclass(frozen=True)
class Block:
    """A busy period within one local day. `start`/`end` are local times; `all_day` covers the whole day."""

    start: datetime
    end: datetime
    tentative: bool = False
    all_day: bool = False


# --- data ------------------------------------------------------------------------------------------------------


def collect(
    gateway: CalendarGateway, calendar_ids: list[str], time_min: datetime, time_max: datetime, tz: ZoneInfo
) -> list[BusyEvent]:
    """Events of every calendar; a calendar shared as free/busy only falls back to its busy periods (never « ? »)."""
    events: list[BusyEvent] = []
    for cid in calendar_ids:
        try:
            events += gateway.busy_events(cid, time_min, time_max, tz)
        except CalendarUnavailable as exc:
            log.warning("printable calendar: using free/busy for a calendar source (%s)", exc)
            start = time_min
            while start < time_max:
                end = min(start + FREE_BUSY_SPAN, time_max)
                events += [BusyEvent(i.start, i.end) for i in gateway.free_busy([cid], start, end)]
                start = end
    return events


def merge(intervals: list[Interval]) -> list[Interval]:
    """Overlapping or touching intervals joined, sorted."""
    out: list[Interval] = []
    for i in sorted(intervals):
        if out and i.start <= out[-1].end:
            out[-1] = Interval(out[-1].start, max(out[-1].end, i.end))
        else:
            out.append(i)
    return out


def subtract(intervals: list[Interval], cuts: list[Interval]) -> list[Interval]:
    """`intervals` minus `cuts` (both merged and sorted)."""
    out: list[Interval] = []
    for i in intervals:
        start = i.start
        for c in cuts:
            if c.end <= start or c.start >= i.end:
                continue
            if c.start > start:
                out.append(Interval(start, c.start))
            start = max(start, c.end)
        if start < i.end:
            out.append(Interval(start, i.end))
    return out


def busy_periods(events: list[BusyEvent]) -> list[tuple[Interval, bool]]:
    """(period, tentative): a fixed event wins over a « ? » one at the same time."""
    firm = merge([Interval(e.start, e.end) for e in events if not e.tentative and e.end > e.start])
    maybe = subtract(merge([Interval(e.start, e.end) for e in events if e.tentative and e.end > e.start]), firm)
    return sorted([(i, False) for i in firm] + [(i, True) for i in maybe], key=lambda p: p[0].start)


def by_day(periods: list[tuple[Interval, bool]], first: date, last: date, tz: ZoneInfo) -> dict[date, list[Block]]:
    """Periods cut at local midnight, kept for the days from `first` to `last`."""
    days: dict[date, list[Block]] = defaultdict(list)
    for period, tentative in periods:
        start, end = period.start.astimezone(tz), period.end.astimezone(tz)
        day = max(start.date(), first)
        while day <= last:
            day_start = datetime.combine(day, time(0), tz)
            day_end = datetime.combine(day + timedelta(days=1), time(0), tz)
            if day_start >= end:
                break
            s, e = max(start, day_start), min(end, day_end)
            days[day].append(Block(s, e, tentative, all_day=(s == day_start and e == day_end)))
            day += timedelta(days=1)
    return dict(days)


def hour_range(days: dict[date, list[Block]]) -> tuple[int, int]:
    """First and last hour of the grid: DEFAULT_HOURS widened to every timed period."""
    lo, hi = DEFAULT_HOURS
    for day, blocks in days.items():
        for b in blocks:
            if b.all_day:
                continue
            lo = min(lo, b.start.hour)
            ends_next_day = b.end.date() > day
            hi = max(hi, 24 if ends_next_day else b.end.hour + (1 if b.end.minute else 0))
    return lo, hi


# --- wording ---------------------------------------------------------------------------------------------------


def updated_line(now: datetime) -> str:
    """'Mis à jour le jeudi 1 octobre 2026 à 14:32'"""
    return f"Mis à jour le {JOURS[now.weekday()]} {now.day} {MOIS[now.month - 1]} {now.year} à {now:%H:%M}"


def period_title(first: date, last: date) -> str:
    """'Calendrier du 5 octobre au 18 octobre 2026' (years and months only repeated when they differ)."""
    end = f"{last.day} {MOIS[last.month - 1]} {last.year}"
    if first == last:
        return f"Calendrier du {JOURS[first.weekday()]} {end}"
    start = f"{first.day} {MOIS[first.month - 1]}" + (f" {first.year}" if first.year != last.year else "")
    return f"Calendrier du {start} au {end}"


MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def day_header(day: date) -> str:
    """'Lun. 5 oct.'"""
    return f"{JOURS[day.weekday()][:3].capitalize()}. {day.day} {MOIS_COURTS[day.month - 1]}"


def hhmm(t: datetime, day: date) -> str:
    return "24:00" if t.date() > day else f"{t:%H:%M}"


# --- PDF -------------------------------------------------------------------------------------------------------

# Very light: grey ink only, thin lines.
INK = HexColor("#4d4d4d")
SOFT = HexColor("#8c8c8c")
FAINT = HexColor("#b4b4b4")
LINE = HexColor("#e2e2e2")
FILL = HexColor("#f3f3f3")
OUTSIDE = HexColor("#fafafa")
WHITE = HexColor("#ffffff")

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 28
LABEL_W = 34
HEADER_H = 18
ALL_DAY_H = 16
GRID_TOP = PAGE_H - MARGIN - 52
GRID_BOTTOM = MARGIN + 14


def _box(c: Canvas, x: float, y: float, w: float, h: float, tentative: bool) -> None:
    c.saveState()
    c.setLineWidth(0.9 if tentative else 0.6)
    c.setStrokeColor(FAINT if not tentative else SOFT)
    c.setFillColor(WHITE if tentative else FILL)
    if tentative:
        c.setLineCap(1)
        c.setDash(0.1, 2.2)  # round caps turn the dashes into dots
    c.rect(x, y, w, h, stroke=1, fill=1)
    c.restoreState()


def _fit(c: Canvas, text: str, size: float, width: float) -> str:
    while text and c.stringWidth(text, "Helvetica", size) > width:
        text = text[:-2] + "…" if len(text) > 2 else ""
    return text


def _block_text(c: Canvas, b: Block, day: date, x: float, top: float, w: float, h: float) -> None:
    c.setFillColor(SOFT)
    times = f"{hhmm(b.start, day)} – {hhmm(b.end, day)}"
    if h >= 19:
        c.setFont("Helvetica", 7)
        c.drawString(x + 3, top - 8, _fit(c, BUSY, 7, w - 6))
        c.drawString(x + 3, top - 16, _fit(c, times, 7, w - 6))
    elif h >= 6:
        size = min(7, h - 1.5)
        c.setFont("Helvetica", size)
        c.drawString(x + 3, top - h / 2 - size / 3, _fit(c, f"{BUSY} {times}", size, w - 6))


def _legend(c: Canvas) -> None:
    c.setFont("Helvetica", 8)
    text_w = c.stringWidth(LEGEND_TENTATIVE, "Helvetica", 8)
    x = PAGE_W - MARGIN - text_w
    y = PAGE_H - MARGIN - 9
    c.setFillColor(SOFT)
    c.drawString(x, y, LEGEND_TENTATIVE)
    _box(c, x - 22, y - 2, 16, 9, tentative=True)
    busy_w = c.stringWidth(BUSY, "Helvetica", 8)
    x -= 22 + 14 + busy_w
    c.setFillColor(SOFT)
    c.drawString(x, y, BUSY)
    _box(c, x - 22, y - 2, 16, 9, tentative=False)


def _week_page(
    c: Canvas,
    monday: date,
    first: date,
    last: date,
    days: dict[date, list[Block]],
    hours: tuple[int, int],
    with_all_day: bool,
    header: tuple[str, str],
    page: tuple[int, int],
) -> None:
    updated, title = header
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, PAGE_H - MARGIN - 9, updated)
    c.setFont("Helvetica", 13)
    c.setFillColor(SOFT)
    c.drawString(MARGIN, PAGE_H - MARGIN - 30, title)
    _legend(c)

    col_w = (PAGE_W - 2 * MARGIN - LABEL_W) / 7
    x0 = MARGIN + LABEL_W
    band_top = GRID_TOP - HEADER_H
    hours_top = band_top - (ALL_DAY_H if with_all_day else 0)
    lo, hi = hours
    hour_h = (hours_top - GRID_BOTTOM) / (hi - lo)

    def y_of(t: datetime, day: date) -> float:
        h = 24.0 if t.date() > day else t.hour + t.minute / 60
        return hours_top - (h - lo) * hour_h

    # Days outside the period: shaded, nothing drawn in them.
    for i in range(7):
        day = monday + timedelta(days=i)
        x = x0 + i * col_w
        inside = first <= day <= last
        if not inside:
            c.setFillColor(OUTSIDE)
            c.rect(x, GRID_BOTTOM, col_w, GRID_TOP - GRID_BOTTOM, stroke=0, fill=1)
        c.setFillColor(SOFT if inside else FAINT)
        c.setFont("Helvetica-Bold" if inside else "Helvetica", 8.5)
        c.drawCentredString(x + col_w / 2, GRID_TOP - 12, day_header(day))

    # Grid: hour lines, day columns, outer frame.
    c.setStrokeColor(LINE)
    c.setLineWidth(0.4)
    c.setFont("Helvetica", 7)
    for h in range(lo, hi + 1):
        y = hours_top - (h - lo) * hour_h
        c.line(x0, y, x0 + 7 * col_w, y)
        if h < hi:
            c.setFillColor(FAINT)
            c.drawRightString(x0 - 4, y - 7, f"{h:02d}:00")
    for i in range(8):
        c.line(x0 + i * col_w, GRID_BOTTOM, x0 + i * col_w, GRID_TOP)
    c.line(x0, GRID_TOP, x0 + 7 * col_w, GRID_TOP)
    c.line(x0, band_top, x0 + 7 * col_w, band_top)
    if with_all_day:
        c.setFillColor(FAINT)
        c.drawRightString(x0 - 4, band_top - 11, "Journée")

    for i in range(7):
        day = monday + timedelta(days=i)
        x = x0 + i * col_w
        for b in days.get(day, []):
            if b.all_day:
                _box(c, x + 2, hours_top + 2, col_w - 4, ALL_DAY_H - 4, b.tentative)
                c.setFillColor(SOFT)
                c.setFont("Helvetica", 7)
                c.drawString(x + 5, hours_top + 5, _fit(c, f"{BUSY} toute la journée", 7, col_w - 10))
                continue
            top, bottom = y_of(b.start, day), y_of(b.end, day)
            _box(c, x + 2, bottom, col_w - 4, max(top - bottom, 1), b.tentative)
            _block_text(c, b, day, x + 2, top, col_w - 4, top - bottom)

    c.setFillColor(FAINT)
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - MARGIN, MARGIN, f"Page {page[0]}/{page[1]}")


def render_pdf(first: date, last: date, days: dict[date, list[Block]], now: datetime) -> bytes:
    """One landscape A4 page per week (Monday to Sunday) covering `first`..`last`; `now` in local time."""
    monday = first - timedelta(days=first.weekday())
    mondays = []
    while monday <= last:
        mondays.append(monday)
        monday += timedelta(days=7)
    with_all_day = any(b.all_day for blocks in days.values() for b in blocks)
    hours = hour_range(days)
    header = (updated_line(now), period_title(first, last))

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    c.setTitle(header[1])
    c.setAuthor("IAfluence")
    for n, monday in enumerate(mondays, start=1):
        _week_page(c, monday, first, last, days, hours, with_all_day, header, (n, len(mondays)))
        c.showPage()
    c.save()
    return buf.getvalue()


def build_pdf(
    gateway: CalendarGateway, calendar_ids: list[str], first: date, last: date, tz: ZoneInfo, now: datetime
) -> bytes:
    time_min = datetime.combine(first, time(0), tz)
    time_max = datetime.combine(last + timedelta(days=1), time(0), tz)
    events = collect(gateway, calendar_ids, time_min, time_max, tz)
    days = by_day(busy_periods(events), first, last, tz)
    return render_pdf(first, last, days, now.astimezone(tz))
