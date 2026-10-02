"""Reports of meetings booked elsewhere (a Google Calendar invitation, a call set up by email…), asked for by hand.

The admin lists the recent Fireflies recordings, picks one and says who the report is for. The meeting is stored
as a `meeting` booking, already completed, and its report starts at the summary step of
app.services.session_reports. The email is always left as a Gmail draft.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import Booking, Customer, SessionReport
from app.services.fireflies import FirefliesGateway, TranscriptMeta
from app.services.settings_service import get_settings
from app.services.stripe_service import upsert_customer

log = logging.getLogger(__name__)

LOOKBACK = timedelta(days=7)
# When Fireflies gives no duration.
DEFAULT_DURATION = timedelta(minutes=30)


class MeetingError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def end_of(meta: TranscriptMeta) -> datetime:
    return meta.start + (timedelta(minutes=meta.duration_min) if meta.duration_min else DEFAULT_DURATION)


def recent(db: Session, fireflies: FirefliesGateway, now: datetime, tz: ZoneInfo) -> list[dict]:
    """Recordings of the last 7 days, newest first. One Fireflies request (FirefliesError is the caller's)."""
    metas = fireflies.list_transcripts(now - LOOKBACK, now)
    reports = dict(
        db.execute(
            select(SessionReport.fireflies_transcript_id, SessionReport.id).where(
                SessionReport.fireflies_transcript_id.in_([m.id for m in metas])
            )
        ).all()
    )
    settings = get_settings(db)
    own = {e.lower() for e in (settings.admin_email, settings.fireflies_email, get_config().mail_from) if e}
    known = dict(
        db.execute(
            select(Customer.email, Customer.name).where(Customer.email.in_({e for m in metas for e in m.emails}))
        ).all()
    )
    out = []
    for m in sorted(metas, key=lambda m: m.start, reverse=True):
        guests = sorted(m.emails - own)
        # A known customer first: their name is already on file.
        suggested = next((e for e in guests if e in known), guests[0] if guests else None)
        out.append(
            {
                "transcript_id": m.id,
                "title": m.title,
                "start": m.start.astimezone(tz).isoformat(),
                "end": end_of(m).astimezone(tz).isoformat(),
                "participants": guests,
                "suggested_email": suggested,
                "suggested_name": known.get(suggested),
                "report_id": reports.get(m.id),
            }
        )
    return out


def create_report(
    db: Session,
    *,
    transcript_id: str,
    title: str | None,
    start: datetime,
    end: datetime,
    name: str,
    email: str,
    locale: str,
    now: datetime,
) -> SessionReport:
    if end <= start:
        raise MeetingError("La fin de la réunion doit être après son début.", 422)
    if db.scalar(select(SessionReport.id).where(SessionReport.fireflies_transcript_id == transcript_id)):
        raise MeetingError("Cette réunion a déjà un compte rendu.")
    customer = upsert_customer(db, name, email)
    booking = Booking(
        kind="meeting",
        customer_id=customer.id,
        start_datetime=start,
        end_datetime=end,
        status="completed",
        title=title,
        locale=locale,
    )
    # Straight to the summary: the recording is already there.
    report = SessionReport(
        booking=booking,
        status="summarizing",
        fireflies_transcript_id=transcript_id,
        waiting_since=now,
        next_attempt_at=now,
    )
    db.add_all([booking, report])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise MeetingError("Cette réunion a déjà un compte rendu.")
    log.info("meeting report %s requested (booking %s)", report.id, booking.id)
    return report
