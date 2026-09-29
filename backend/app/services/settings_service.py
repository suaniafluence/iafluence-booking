from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AvailabilityRule, CalendarSource, Settings
from app.services.availability import SlotRules


def get_settings(db: Session) -> Settings:
    settings = db.scalar(select(Settings).order_by(Settings.id))
    if settings is None:
        raise RuntimeError("settings row missing — run scripts/seed_settings.py")
    return settings


def slot_rules(db: Session, settings: Settings | None = None) -> SlotRules:
    s = settings or get_settings(db)
    weekly: dict[int, list] = defaultdict(list)
    for rule in db.scalars(select(AvailabilityRule).order_by(AvailabilityRule.weekday, AvailabilityRule.start_time)):
        weekly[rule.weekday].append((rule.start_time, rule.end_time))
    return SlotRules(
        tz=ZoneInfo(s.timezone),
        weekly=dict(weekly),
        duration=timedelta(minutes=s.booking_duration_min),
        step=timedelta(minutes=s.slot_step_min),
        min_notice=timedelta(minutes=s.minimum_notice_min),
        max_window=timedelta(days=s.maximum_window_days),
        buffer_before=timedelta(minutes=s.buffer_before_min),
        buffer_after=timedelta(minutes=s.buffer_after_min),
    )


def busy_calendar_ids(db: Session, settings: Settings | None = None) -> list[str]:
    """All enabled sources plus the calendar where bookings are written (R04)."""
    s = settings or get_settings(db)
    ids = list(db.scalars(select(CalendarSource.google_calendar_id).where(CalendarSource.enabled)))
    if s.booking_calendar_id and s.booking_calendar_id not in ids:
        ids.append(s.booking_calendar_id)
    return ids
