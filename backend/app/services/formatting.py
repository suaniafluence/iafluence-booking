"""French date/time formatting that does not depend on the OS locale."""

from datetime import datetime
from zoneinfo import ZoneInfo

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def long_date(dt: datetime, tz: str) -> str:
    """'Jeudi 8 octobre 2026'"""
    d = dt.astimezone(ZoneInfo(tz))
    return f"{JOURS[d.weekday()].capitalize()} {d.day} {MOIS[d.month - 1]} {d.year}"


def hour_range(start: datetime, end: datetime, tz: str, sep: str = "h") -> str:
    """'14h00 - 15h00' (sep='h') or '14:00 - 15:00' (sep=':')"""
    z = ZoneInfo(tz)
    s, e = start.astimezone(z), end.astimezone(z)
    return f"{s:%H}{sep}{s:%M} - {e:%H}{sep}{e:%M}"


def short_date(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y")


def hours(n: int) -> str:
    return f"{n} heure" if n == 1 else f"{n} heures"
