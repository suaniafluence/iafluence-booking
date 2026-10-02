"""Date/time formatting (fr, en, es) that does not depend on the OS locale."""

from datetime import datetime
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}
MONTHS = {
    "fr": [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
    "es": [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ],
}


def long_date(dt: datetime, tz: str, locale: str = "fr") -> str:
    """'Jeudi 8 octobre 2026' · 'Thursday 8 October 2026' · 'Jueves, 8 de octubre de 2026'"""
    d = dt.astimezone(ZoneInfo(tz))
    weekday, month = WEEKDAYS[locale][d.weekday()].capitalize(), MONTHS[locale][d.month - 1]
    if locale == "es":
        return f"{weekday}, {d.day} de {month} de {d.year}"
    return f"{weekday} {d.day} {month} {d.year}"


def hour_range(start: datetime, end: datetime, tz: str, sep: str = "h") -> str:
    """'14h00 - 15h00' (sep='h') or '14:00 - 15:00' (sep=':')"""
    z = ZoneInfo(tz)
    s, e = start.astimezone(z), end.astimezone(z)
    return f"{s:%H}{sep}{s:%M} - {e:%H}{sep}{e:%M}"


def short_date(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y")


HOUR_WORDS = {"fr": ("heure", "heures"), "en": ("hour", "hours"), "es": ("hora", "horas")}


def hours(n: int, locale: str = "fr") -> str:
    one, many = HOUR_WORDS[locale]
    return f"{n} {one if n == 1 else many}"


def tz_city(tz: str) -> str:
    """'America/Argentina/Buenos_Aires' -> 'Buenos Aires'"""
    return tz.rsplit("/", 1)[-1].replace("_", " ")


def inline_date(dt: datetime, tz: str, locale: str = "fr") -> str:
    """long_date in the middle of a sentence: 'du jeudi 8 octobre 2026', 'del jueves, 8 de octubre…', but
    'on Thursday 8 October 2026'."""
    date = long_date(dt, tz, locale)
    return date if locale == "en" else date.lower()
