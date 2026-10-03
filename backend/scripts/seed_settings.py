"""Create the settings row and default weekly hours if they do not exist yet.

    uv run python -m scripts.seed_settings --admin-email contact@iafluence.fr --booking-calendar ID

Idempotent: existing settings are only updated for the options passed on the command line.
"""

import argparse
from datetime import time

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AvailabilityRule, Settings, StaffUser

DEFAULT_WEEKLY = {
    0: [(time(9), time(18))],
    1: [(time(9), time(18))],
    2: [(time(9), time(18))],
    3: [(time(9), time(18))],
    4: [(time(9), time(17))],
}


def seed(admin_email: str | None = None, booking_calendar: str | None = None) -> None:
    with SessionLocal() as db:
        settings = db.scalar(select(Settings))
        if settings is None:
            settings = Settings(
                booking_duration_min=60,
                slot_step_min=60,
                minimum_notice_min=24 * 60,
                maximum_window_days=30,
                buffer_before_min=15,
                buffer_after_min=15,
                timezone="Europe/Paris",
                booking_calendar_id="primary",
                meet_enabled=True,
                admin_email="",
                consultant_name="Suan Tay",
            )
            db.add(settings)
            print("settings created")
        if admin_email:
            settings.admin_email = admin_email
            # V3: this address signs in with Google to both the admin area and the cockpit.
            email = admin_email.lower()
            if db.scalar(select(StaffUser.id).where(StaffUser.email == email)) is None:
                db.add(StaffUser(email=email, name=settings.consultant_name, is_admin=True, is_consultant=True))
                print(f"staff account created for {email} (admin + consultant)")
        if booking_calendar:
            settings.booking_calendar_id = booking_calendar

        if db.scalar(select(AvailabilityRule.id).limit(1)) is None:
            for weekday, intervals in DEFAULT_WEEKLY.items():
                for start, end in intervals:
                    db.add(AvailabilityRule(weekday=weekday, start_time=start, end_time=end))
            print("default weekly hours created (Mon-Thu 09-18, Fri 09-17)")
        db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-email")
    parser.add_argument("--booking-calendar", help="Google calendar id for 'IAfluence - Conseil clients'")
    args = parser.parse_args()
    seed(args.admin_email, args.booking_calendar)
