"""Printable calendar: busy periods of every calendar, « Occupé » only, dotted when not fixed yet."""

import io
from datetime import date, datetime, timedelta

import pytest
from reportlab.pdfgen.canvas import Canvas

from app.services import calendar_print as cp
from app.services.availability import Interval
from app.services.calendar_service import BusyEvent, CalendarUnavailable
from tests.conftest import ADMIN_PASSWORD, PARIS, paris


def iv(d1, h1, d2, h2, m1=0, m2=0) -> Interval:
    return Interval(paris(2026, 10, d1, h1, m1), paris(2026, 10, d2, h2, m2))


# --- periods ---------------------------------------------------------------------------------------------------


def test_merge_joins_overlapping_and_touching_periods():
    assert cp.merge([iv(5, 11, 5, 12), iv(5, 9, 5, 10), iv(5, 10, 5, 11), iv(5, 14, 5, 15), iv(5, 14, 5, 14, 0, 30)]) == [
        iv(5, 9, 5, 12),
        iv(5, 14, 5, 15),
    ]
    assert cp.merge([iv(5, 9, 5, 12), iv(5, 10, 5, 11)]) == [iv(5, 9, 5, 12)]
    assert cp.merge([]) == []


def test_subtract_cuts_around_fixed_periods():
    assert cp.subtract([iv(5, 9, 5, 17)], [iv(5, 8, 5, 10), iv(5, 12, 5, 13), iv(5, 16, 5, 18)]) == [
        iv(5, 10, 5, 12),
        iv(5, 13, 5, 16),
    ]
    assert cp.subtract([iv(5, 9, 5, 10)], [iv(5, 9, 5, 10)]) == []
    assert cp.subtract([iv(5, 9, 5, 10)], [iv(5, 10, 5, 11), iv(5, 7, 5, 9)]) == [iv(5, 9, 5, 10)]
    assert cp.subtract([iv(5, 9, 5, 12)], [iv(5, 9, 5, 10)]) == [iv(5, 10, 5, 12)]


def test_a_fixed_event_wins_over_a_tentative_one():
    events = [
        BusyEvent(paris(2026, 10, 5, 12), paris(2026, 10, 5, 14), True),
        BusyEvent(paris(2026, 10, 5, 13), paris(2026, 10, 5, 13, 30)),
        BusyEvent(paris(2026, 10, 5, 9), paris(2026, 10, 5, 10)),
        BusyEvent(paris(2026, 10, 5, 9, 30), paris(2026, 10, 5, 10, 30), True),
        BusyEvent(paris(2026, 10, 5, 16), paris(2026, 10, 5, 16)),  # empty: ignored
        BusyEvent(paris(2026, 10, 5, 17), paris(2026, 10, 5, 17), True),
    ]
    assert cp.busy_periods(events) == [
        (iv(5, 9, 5, 10), False),
        (iv(5, 10, 5, 10, 0, 30), True),
        (iv(5, 12, 5, 13), True),
        (iv(5, 13, 5, 13, 0, 30), False),
        (iv(5, 13, 5, 14, 30, 0), True),
    ]


def test_by_day_cuts_at_midnight_and_keeps_the_period_only():
    periods = [
        (iv(4, 22, 5, 2), False),  # starts before the period
        (iv(6, 0, 7, 0), True),  # a whole day
        (iv(7, 18, 9, 9), False),  # over two midnights
        (iv(9, 23, 10, 1), False),  # ends after the period
        (iv(12, 9, 12, 10), False),  # after the period
    ]
    days = cp.by_day(periods, date(2026, 10, 5), date(2026, 10, 9), PARIS)
    assert days == {
        date(2026, 10, 5): [cp.Block(paris(2026, 10, 5, 0), paris(2026, 10, 5, 2))],
        date(2026, 10, 6): [cp.Block(paris(2026, 10, 6, 0), paris(2026, 10, 7, 0), True, all_day=True)],
        date(2026, 10, 7): [cp.Block(paris(2026, 10, 7, 18), paris(2026, 10, 8, 0))],
        date(2026, 10, 8): [cp.Block(paris(2026, 10, 8, 0), paris(2026, 10, 9, 0), all_day=True)],
        date(2026, 10, 9): [
            cp.Block(paris(2026, 10, 9, 0), paris(2026, 10, 9, 9)),
            cp.Block(paris(2026, 10, 9, 23), paris(2026, 10, 10, 0)),
        ],
    }


def test_by_day_uses_local_days_across_a_dst_change():
    # 25 October 2026: clocks go back, the day lasts 25 hours.
    days = cp.by_day([(iv(25, 0, 26, 0), False)], date(2026, 10, 25), date(2026, 10, 25), PARIS)
    assert days[date(2026, 10, 25)][0].all_day


def test_hour_range_widens_to_every_timed_period():
    assert cp.hour_range({}) == (8, 20)
    one = date(2026, 10, 5)
    assert cp.hour_range({one: [cp.Block(paris(2026, 10, 5, 9), paris(2026, 10, 5, 10))]}) == (8, 20)
    assert cp.hour_range({one: [cp.Block(paris(2026, 10, 5, 7, 30), paris(2026, 10, 5, 20, 15))]}) == (7, 21)
    assert cp.hour_range({one: [cp.Block(paris(2026, 10, 5, 8), paris(2026, 10, 5, 20))]}) == (8, 20)
    assert cp.hour_range({one: [cp.Block(paris(2026, 10, 5, 22), paris(2026, 10, 6, 0))]}) == (8, 24)
    assert cp.hour_range({one: [cp.Block(paris(2026, 10, 5, 0), paris(2026, 10, 6, 0), all_day=True)]}) == (8, 20)


def test_collect_falls_back_to_free_busy_for_a_calendar_shared_as_free_busy_only(fakes, caplog):
    cal = fakes["calendar"]
    cal.listed["perso"] = [(paris(2026, 10, 5, 9), paris(2026, 10, 5, 10), True)]
    cal.list_errors.add("travail")
    cal.busy["travail"] = [(paris(2026, 10, 5, 14), paris(2026, 10, 5, 15))]
    events = cp.collect(cal, ["perso", "travail"], paris(2026, 10, 5, 0), paris(2026, 10, 6, 0), PARIS)
    assert events == [
        BusyEvent(paris(2026, 10, 5, 9), paris(2026, 10, 5, 10), True),
        BusyEvent(paris(2026, 10, 5, 14), paris(2026, 10, 5, 15), False),
    ]
    assert cal.freebusy_calls == [["travail"]]
    assert "travail" not in caplog.text


def test_collect_asks_free_busy_month_by_month_over_a_long_period(fakes):
    cal = fakes["calendar"]
    cal.list_errors.add("travail")
    seen = []
    cal.free_busy = lambda ids, t_min, t_max: seen.append((t_min, t_max)) or []
    cp.collect(cal, ["travail"], paris(2026, 1, 1, 0), paris(2026, 3, 15, 0), PARIS)
    assert seen == [
        (paris(2026, 1, 1, 0), paris(2026, 2, 1, 0)),
        (paris(2026, 2, 1, 0), paris(2026, 3, 4, 0)),
        (paris(2026, 3, 4, 0), paris(2026, 3, 15, 0)),
    ]


def test_collect_fails_when_a_calendar_cannot_be_read_at_all(fakes):
    cal = fakes["calendar"]
    cal.list_errors.add("travail")
    cal.errors.add("travail")
    with pytest.raises(CalendarUnavailable):
        cp.collect(cal, ["travail"], paris(2026, 10, 5, 0), paris(2026, 10, 6, 0), PARIS)


# --- wording ---------------------------------------------------------------------------------------------------


def test_updated_line():
    assert cp.updated_line(paris(2026, 10, 1, 9, 5)) == "Mis à jour le jeudi 1 octobre 2026 à 09:05"


@pytest.mark.parametrize(
    "first, last, title",
    [
        (date(2026, 10, 5), date(2026, 10, 18), "Calendrier du 5 octobre au 18 octobre 2026"),
        (date(2026, 12, 28), date(2027, 1, 10), "Calendrier du 28 décembre 2026 au 10 janvier 2027"),
        (date(2026, 10, 8), date(2026, 10, 8), "Calendrier du jeudi 8 octobre 2026"),
    ],
)
def test_period_title(first, last, title):
    assert cp.period_title(first, last) == title


def test_day_header_and_times():
    assert cp.day_header(date(2026, 10, 5)) == "Lun. 5 oct."
    assert cp.day_header(date(2026, 7, 12)) == "Dim. 12 juil."
    assert cp.day_header(date(2026, 5, 6)) == "Mer. 6 mai"
    day = date(2026, 10, 5)
    assert cp.hhmm(paris(2026, 10, 5, 9, 30), day) == "09:30"
    assert cp.hhmm(paris(2026, 10, 6, 0), day) == "24:00"


# --- PDF -------------------------------------------------------------------------------------------------------


@pytest.fixture
def drawn(monkeypatch):
    """Every text written on the pages and every busy box drawn: (x, y, w, h, tentative)."""
    out = {"text": [], "boxes": [], "pages": 0}
    for name in ("drawString", "drawCentredString", "drawRightString"):
        original = getattr(Canvas, name)

        def spy(self, x, y, text, *a, _original=original, **kw):
            out["text"].append(text)
            return _original(self, x, y, text, *a, **kw)

        monkeypatch.setattr(Canvas, name, spy)
    real_box, real_show = cp._box, Canvas.showPage

    def box(c, x, y, w, h, tentative):
        out["boxes"].append((round(x), round(y), round(w), round(h), tentative))
        real_box(c, x, y, w, h, tentative)

    def show(self):
        out["pages"] += 1
        real_show(self)

    monkeypatch.setattr(cp, "_box", box)
    monkeypatch.setattr(Canvas, "showPage", show)
    return out


def test_pdf_has_one_page_per_week_the_update_date_and_only_busy_labels(drawn):
    days = {
        date(2026, 10, 6): [
            cp.Block(paris(2026, 10, 6, 9), paris(2026, 10, 6, 10, 30)),
            cp.Block(paris(2026, 10, 6, 12), paris(2026, 10, 6, 12, 30), True),
            cp.Block(paris(2026, 10, 6, 15), paris(2026, 10, 6, 15, 5)),
        ],
        date(2026, 10, 12): [cp.Block(paris(2026, 10, 12, 0), paris(2026, 10, 13, 0), True, all_day=True)],
    }
    pdf = cp.render_pdf(date(2026, 10, 6), date(2026, 10, 12), days, paris(2026, 10, 1, 14, 32))

    assert pdf.startswith(b"%PDF-")
    assert drawn["pages"] == 2  # week of the 5th, week of the 12th
    text = drawn["text"]
    assert text.count("Mis à jour le jeudi 1 octobre 2026 à 14:32") == 2
    assert text.count("Calendrier du 6 octobre au 12 octobre 2026") == 2
    assert text.count("Pas encore fixé ou pas sûr") == 2
    assert text.count("Page 1/2") == text.count("Page 2/2") == 1
    assert ["Lun. 5 oct.", "Mar. 6 oct.", "Dim. 11 oct.", "Lun. 12 oct.", "Dim. 18 oct."] == [
        t for t in text if t in ("Lun. 5 oct.", "Mar. 6 oct.", "Dim. 11 oct.", "Lun. 12 oct.", "Dim. 18 oct.")
    ]
    assert "Occupé" in text and "09:00 – 10:30" in text  # tall block: two lines
    assert "Occupé 12:00 – 12:30" in text  # short block: one line
    assert not any("15:05" in t for t in text)  # 5 minutes: too small for any text
    assert "Occupé toute la journée" in text and text.count("Journée") == 2
    assert {"08:00", "19:00"} <= set(text) and "20:00" not in text

    # Legend (dotted sample, then plain) then the blocks; only the « ? » ones are dotted.
    legend = [True, False]
    assert [b[4] for b in drawn["boxes"]] == legend + [False, True, False] + legend + [True]
    first_page_blocks = drawn["boxes"][2:5]
    assert all(b[2] == first_page_blocks[0][2] for b in first_page_blocks)  # same column width
    nine_to_ten_thirty, noon_to_half_past = first_page_blocks[0][3], first_page_blocks[1][3]
    assert nine_to_ten_thirty == pytest.approx(3 * noon_to_half_past, abs=1)


def test_pdf_without_whole_days_has_no_journee_band(drawn):
    cp.render_pdf(date(2026, 10, 5), date(2026, 10, 5), {}, paris(2026, 10, 1, 14, 32))
    assert drawn["pages"] == 1 and "Journée" not in drawn["text"]
    assert "Calendrier du lundi 5 octobre 2026" in drawn["text"]


def test_fit_shortens_text_to_the_width():
    c = Canvas(io.BytesIO())
    assert cp._fit(c, "Occupé 09:00 – 10:00", 7, 1000) == "Occupé 09:00 – 10:00"
    short = cp._fit(c, "Occupé 09:00 – 10:00", 7, 40)
    assert short.endswith("…") and c.stringWidth(short, "Helvetica", 7) <= 40
    assert cp._fit(c, "Occupé", 7, 1) == ""


# --- admin endpoint (real PostgreSQL) --------------------------------------------------------------------------


def login(client):
    assert client.post("/api/admin/login", json={"password": ADMIN_PASSWORD}).status_code == 200


URL = "/api/admin/calendar.pdf?start=2026-10-05&end=2026-10-18"


def test_calendar_pdf_requires_the_admin_session(client):
    assert client.get(URL).status_code == 401


def test_calendar_pdf_prints_every_enabled_calendar(client, fakes, drawn):
    cal = fakes["calendar"]
    cal.listed["cal-principal"] = [(paris(2026, 10, 6, 9), paris(2026, 10, 6, 10), False)]
    cal.listed["cal-formation"] = [(paris(2026, 10, 7, 14), paris(2026, 10, 7, 16), True)]
    cal.listed["cal-off"] = [(paris(2026, 10, 8, 17), paris(2026, 10, 8, 18), False)]
    cal.list_errors.add("booking-cal")
    cal.busy["booking-cal"] = [(paris(2026, 10, 9, 11), paris(2026, 10, 9, 12))]
    login(client)

    r = client.get(URL)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="calendrier-2026-10-05-au-2026-10-18.pdf"'
    assert r.headers["cache-control"] == "private, no-store"
    assert r.content.startswith(b"%PDF-")

    assert sorted(cal.list_calls) == ["booking-cal", "cal-formation", "cal-principal"]  # not the disabled one
    assert cal.freebusy_calls == [["booking-cal"]]
    text = drawn["text"]
    assert "Mis à jour le lundi 5 octobre 2026 à 08:00" in text  # NOW, Paris time
    assert {"09:00 – 10:00", "14:00 – 16:00", "11:00 – 12:00"} <= set(text)
    assert "17:00 – 18:00" not in text  # the disabled calendar is ignored
    assert [b[4] for b in drawn["boxes"]] == [True, False, False, True, False] + [True, False]


@pytest.mark.parametrize(
    "query, message",
    [
        ("start=2026-10-18&end=2026-10-05", "La date de fin doit être le même jour ou après la date de début."),
        ("start=2026-10-05&end=2027-10-06", "Période trop longue : 366 jours au plus."),
    ],
)
def test_calendar_pdf_rejects_bad_periods(client, query, message):
    login(client)
    r = client.get(f"/api/admin/calendar.pdf?{query}")
    assert r.status_code == 422 and r.json()["detail"] == message


def test_calendar_pdf_accepts_the_longest_period(client):
    login(client)
    start = date(2026, 10, 5)
    end = start + timedelta(days=cp.MAX_DAYS - 1)
    assert client.get(f"/api/admin/calendar.pdf?start={start}&end={end}").status_code == 200


def test_calendar_pdf_when_a_calendar_is_down(client, fakes):
    fakes["calendar"].list_errors.add("cal-principal")
    fakes["calendar"].errors.add("cal-principal")
    login(client)
    r = client.get(URL)
    assert r.status_code == 502 and r.json()["detail"] == "Un agenda Google ne répond pas. Réessayez dans un instant."


def test_build_pdf_asks_for_whole_local_days(fakes):
    cal = fakes["calendar"]
    seen = []
    cal.busy_events = lambda cid, t_min, t_max, tz: seen.append((t_min, t_max)) or []
    cp.build_pdf(cal, ["a"], date(2026, 10, 24), date(2026, 10, 25), PARIS, datetime(2026, 10, 1, 12, tzinfo=PARIS))
    assert seen == [(paris(2026, 10, 24, 0), paris(2026, 10, 26, 0))]
