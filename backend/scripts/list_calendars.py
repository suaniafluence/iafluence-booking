"""List the calendars visible to the IAfluence Gmail account, and optionally register them.

    uv run python -m scripts.list_calendars            # print id, name, access role
    uv run python -m scripts.list_calendars --add ID "Nom"   # add/enable a busy source

Calendars from other accounts must first be shared with this Gmail account
(permission "See only free/busy" is enough).
"""

import sys

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import CalendarSource
from app.services.google_client import calendar_api


def list_calendars() -> None:
    page_token = None
    print(f"{'ACCESS':<16} {'NAME':<35} ID")
    while True:
        resp = calendar_api().calendarList().list(pageToken=page_token).execute()
        for cal in resp.get("items", []):
            print(f"{cal.get('accessRole', ''):<16} {cal.get('summary', '')[:35]:<35} {cal['id']}")
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def add_source(calendar_id: str, name: str) -> None:
    with SessionLocal() as db:
        db.execute(
            pg_insert(CalendarSource)
            .values(google_calendar_id=calendar_id, name=name, enabled=True)
            .on_conflict_do_update(index_elements=[CalendarSource.google_calendar_id], set_={"name": name, "enabled": True})
        )
        db.commit()
    print(f"calendar source '{name}' enabled")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--add":
        add_source(sys.argv[2], sys.argv[3])
    else:
        list_calendars()
