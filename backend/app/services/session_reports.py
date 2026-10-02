"""Session reports: Fireflies transcript -> summary by the Codex agent -> Gmail draft to the client.

    waiting_transcript -> summarizing -> ready -> drafted
                  \\             \\
                   \\             -> failed (Codex not connected, invalid output twice…) + admin alert
                    -> drafted without summary after FIREFLIES_MAX_WAIT_HOURS + admin alert

A drafted report whose email Gmail refused has delivery "failed": the admin can prepare it again (retry_email).

The end-of-session job (follow_up) creates the report instead of the V1 email. `process` then runs every minute:
- one Fireflies request lists the recordings of every due session (quota-friendly), matched on the start time
  (± 15 min) and the client email among the participants, or the Meet link;
- a report being summarized is claimed for the length of a Codex turn instead of holding a row lock;
- emails leave after the commit, so a crash can lose one but never send it twice (same rule as follow_up).
The transcript is read from Fireflies when needed and never stored nor logged: only the summary and the PNG are,
for REPORT_RETENTION_DAYS.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, defer, joinedload

from app.config import get_config
from app.db import SessionLocal
from app.i18n import text
from app.models import Booking, SessionReport
from app.services import formatting as fmt
from app.services import fireflies_account, notifications, report_content
from app.services.codex import CodexGateway, CodexNotConnected, CodexTurnFailed, CodexUnavailable
from app.services.email_service import Mailer, render, send_safely
from app.services.fireflies import FirefliesError, FirefliesGateway, TranscriptMeta, normalize_meet_url
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)

MATCH_WINDOW = timedelta(minutes=15)
# A claim outlives the Codex turn timeout by this much before another process may take the report over.
CLAIM_MARGIN = timedelta(minutes=5)
# First try, then one more after an invalid answer or a Codex error.
MAX_SUMMARY_ATTEMPTS = 2
IMAGE_CID = "compte-rendu"

# French subjects (other languages: app.i18n).
SUBJECT_NEXT = text("fr", "subject_report_next")
SUBJECT_LAST = text("fr", "subject_report_last")
SUBJECT_NEXT_V1 = text("fr", "subject_next_link")
SUBJECT_LAST_V1 = text("fr", "subject_last_thanks")
ALERT_SUBJECT = "COMPTE RENDU — action requise"
RETRY_HINT = "Cliquez sur « Relancer » dans l'admin, ou sur « Créer le brouillon sans résumé »."
GMAIL_FAILED = "L'email n'a pas pu être préparé dans Gmail (voir les logs de l'API)."


@dataclass
class Gateways:
    mailer: Mailer
    fireflies: FirefliesGateway
    codex: CodexGateway


@dataclass
class Email:
    to: str
    subject: str
    body: str
    as_draft: bool
    html: str | None = None
    images: Mapping[str, bytes] = field(default_factory=dict)
    report_id: int | None = None


class ReportActionError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def enabled(db: Session) -> bool:
    """Codex app-server configured and a Fireflies key (connected in the admin, or FIREFLIES_API_KEY)."""
    cfg = get_config()
    return cfg.fake_integrations or (cfg.codex_enabled and bool(fireflies_account.api_key(db)))


def poll_interval() -> timedelta:
    return timedelta(seconds=get_config().fireflies_poll_seconds)


def max_wait() -> timedelta:
    return timedelta(hours=get_config().fireflies_max_wait_hours)


# --- creation (end-of-session job) -------------------------------------------------------------------------------


def create_for(db: Session, booking: Booking, now: datetime) -> None:
    """Called by follow_up in its transaction, instead of preparing the email right away."""
    db.add(
        SessionReport(
            booking_id=booking.id,
            status="waiting_transcript",
            waiting_since=now,
            # Fireflies needs a few minutes to process the recording.
            next_attempt_at=now + poll_interval(),
        )
    )


# --- emails ------------------------------------------------------------------------------------------------------


def summary_sections(summary: dict, locale: str = "fr") -> list[tuple[str, list[str]]]:
    titles = report_content.SECTION_TITLES[locale]
    return [(titles[key], summary.get(key) or []) for key, _ in report_content.SECTIONS if summary.get(key)]


def compose(db: Session, report: SessionReport, now: datetime, *, with_summary: bool, force_draft: bool = False):
    """The client email of a report, or the reason there is none. Marks the report drafted (or failed)."""
    if report.booking.kind != "session":
        return _compose_other(db, report, now, with_summary=with_summary, force_draft=force_draft)
    booking = report.booking
    purchase, customer = booking.purchase, booking.customer
    settings = get_settings(db)
    locale = purchase.locale
    last = purchase.hours_remaining < 1
    reason = None
    token = None
    if purchase.payment_status != "paid":
        reason = "Achat remboursé : aucun email préparé."
    elif not last:
        token = notifications.active_token(db, purchase.id)
        if token is None:
            reason = "Lien de réservation révoqué : aucun email préparé."
    if reason:
        report.status, report.error, report.claimed_until = "failed", reason, None
        return None

    ctx = {
        "name": customer.name,
        "last": last,
        "hours_remaining": purchase.hours_remaining,
        "hours_remaining_label": fmt.hours(purchase.hours_remaining, locale),
        "hours_purchased_label": fmt.hours(purchase.hours_purchased, locale),
        "booking_url": notifications.booking_url(token, locale) if token else None,
        "shop_url": get_config().shop_url,
        "consultant_name": settings.consultant_name,
    }
    with_summary = with_summary and report.summary is not None
    html, images = None, {}
    if with_summary:
        ctx |= {
            "date_long": fmt.inline_date(booking.start_datetime, settings.timezone, locale),
            "sections": summary_sections(report.summary, locale),
            "image_cid": IMAGE_CID if report.image_png else None,
        }
        body = render(f"{locale}/session_report.txt", **ctx)
        html = render(f"{locale}/session_report.html", **ctx)
        images = {IMAGE_CID: report.image_png} if report.image_png else {}
        subject = text(locale, "subject_report_last" if last else "subject_report_next")
    else:
        body = render(f"{locale}/{'last_session_thanks' if last else 'next_session_link'}.txt", **ctx)
        subject = text(locale, "subject_last_thanks" if last else "subject_next_link")

    # A generated summary is reviewed before it reaches the client, unless the admin opted out.
    auto = customer.auto_send_next_link and (not with_summary or settings.send_reports_without_review)
    email = Email(customer.email, subject, body, force_draft or not auto, html, images, report.id)
    return _drafted(report, now, email, with_summary)


def _compose_other(db: Session, report: SessionReport, now: datetime, *, with_summary: bool, force_draft: bool):
    """Discovery call: the report, or thanks and where to buy consulting hours. Meeting booked elsewhere: the report
    only, always as a draft (the admin asked for it by hand)."""
    booking, customer, settings = report.booking, report.booking.customer, get_settings(db)
    locale, kind = booking.client_locale, booking.kind
    date_long = fmt.inline_date(booking.start_datetime, settings.timezone, locale)
    with_summary = with_summary and report.summary is not None
    if not with_summary and kind == "meeting":
        report.status, report.claimed_until = "failed", None
        report.error = "Pas de compte rendu : aucun email préparé pour cette réunion."
        return None
    ctx = {
        "name": customer.name,
        "kind": kind,
        "date_long": date_long,
        "shop_url": get_config().shop_url,
        "consultant_name": settings.consultant_name,
    }
    html, images = None, {}
    if with_summary:
        ctx |= {
            "sections": summary_sections(report.summary, locale),
            "image_cid": IMAGE_CID if report.image_png else None,
        }
        body = render(f"{locale}/report.txt", **ctx)
        html = render(f"{locale}/report.html", **ctx)
        images = {IMAGE_CID: report.image_png} if report.image_png else {}
        subject = (
            text(locale, "subject_discovery_report")
            if kind == "discovery"
            else text(locale, "subject_meeting_report", date=fmt.short_date(booking.start_datetime, settings.timezone))
        )
    else:
        body = render(f"{locale}/discovery_thanks.txt", **ctx)
        subject = text(locale, "subject_discovery_thanks")
    auto = (
        kind == "discovery"
        and customer.auto_send_next_link
        and (not with_summary or settings.send_reports_without_review)
    )
    email = Email(customer.email, subject, body, force_draft or not auto, html, images, report.id)
    return _drafted(report, now, email, with_summary)


def _drafted(report: SessionReport, now: datetime, email: Email, with_summary: bool) -> Email:
    report.status, report.claimed_until, report.next_attempt_at = "drafted", None, None
    report.delivery = "draft" if email.as_draft else "sent"
    report.with_summary = with_summary
    report.drafted_at = now
    return email


def deliver(mailer: Mailer, email: Email) -> None:
    """After the commit. A failure is logged by send_safely and shown on the report, which can then be retried."""
    ok = send_safely(
        mailer, email.to, email.subject, email.body, as_draft=email.as_draft, html=email.html, images=email.images
    )
    if not ok and email.report_id is not None:
        with SessionLocal() as db:
            db.execute(
                update(SessionReport)
                .where(SessionReport.id == email.report_id)
                .values(delivery="failed", error=GMAIL_FAILED)
            )
            db.commit()


def alert(db: Session, report: SessionReport, problem: str, action: str) -> Email:
    booking, settings = report.booking, get_settings(db)
    body = render(
        "admin_report_alert.txt",
        name=booking.customer.name,
        email=booking.customer.email,
        date_short=fmt.short_date(booking.start_datetime, settings.timezone),
        hour_range=fmt.hour_range(booking.start_datetime, booking.end_datetime, settings.timezone, ":"),
        problem=problem,
        action=action,
        admin_url=f"{get_config().public_base_url.rstrip('/')}/admin",
    )
    return Email(settings.admin_email, ALERT_SUBJECT, body, as_draft=False)


def _send_all(mailer: Mailer, emails: list[Email]) -> None:
    for email in emails:
        deliver(mailer, email)


# --- step 1: find the transcript ----------------------------------------------------------------------------------


def match(booking: Booking, metas: list[TranscriptMeta], taken: set[str]) -> TranscriptMeta | None:
    """Recording of this session: started within ± 15 min, with the client among the participants or on its Meet."""
    email = booking.customer.email.lower()
    meet = normalize_meet_url(booking.meet_url)
    candidates = [
        m
        for m in metas
        if m.id not in taken
        and abs(m.start - booking.start_datetime) <= MATCH_WINDOW
        and (email in {e.lower() for e in m.emails} or (meet is not None and normalize_meet_url(m.meeting_link) == meet))
    ]
    return min(candidates, key=lambda m: abs(m.start - booking.start_datetime), default=None)


def poll_transcripts(gw: Gateways, now: datetime) -> None:
    emails: list[Email] = []
    with SessionLocal() as db:
        due = db.scalars(
            select(SessionReport)
            .options(joinedload(SessionReport.booking).joinedload(Booking.customer))
            .where(
                SessionReport.status == "waiting_transcript",
                or_(SessionReport.next_attempt_at <= now, SessionReport.waiting_since <= now - max_wait()),
            )
            .order_by(SessionReport.next_attempt_at)
            .with_for_update(of=SessionReport, skip_locked=True)
        ).all()
        waiting = []
        for report in due:
            if now - report.waiting_since >= max_wait():
                problem = f"Aucune transcription Fireflies au bout de {get_config().fireflies_max_wait_hours} h."
                email = compose(db, report, now, with_summary=False)
                if email:
                    report.error = problem
                    emails += [email, alert(db, report, problem, "L'email a été préparé sans compte rendu.")]
            elif report.fireflies_transcript_id:
                # Found earlier but Fireflies was still processing it: read it again, no new search.
                report.status, report.next_attempt_at = "summarizing", now
            else:
                waiting.append(report)
        if waiting:
            _look_up(db, gw.fireflies, waiting, now)
        db.commit()
    _send_all(gw.mailer, emails)


def _look_up(db: Session, fireflies: FirefliesGateway, reports: list[SessionReport], now: datetime) -> None:
    starts = [r.booking.start_datetime for r in reports]
    try:
        metas = fireflies.list_transcripts(min(starts) - MATCH_WINDOW, max(starts) + MATCH_WINDOW)
    except FirefliesError as e:
        log.warning("Fireflies lookup failed for %d session(s): %s", len(reports), e)
        metas, error = [], str(e)
    else:
        error = None
    taken = set(
        db.scalars(
            select(SessionReport.fireflies_transcript_id).where(
                SessionReport.fireflies_transcript_id.in_([m.id for m in metas])
            )
        )
    )
    for report in reports:
        report.transcript_attempts += 1
        found = match(report.booking, metas, taken)
        if found is None:
            report.next_attempt_at = now + poll_interval()
            report.error = error
            continue
        taken.add(found.id)
        report.fireflies_transcript_id = found.id
        report.status, report.next_attempt_at, report.error = "summarizing", now, None


# --- step 2: summary by the Codex agent --------------------------------------------------------------------------


def _claim(now: datetime) -> int | None:
    with SessionLocal() as db:
        report = db.scalar(
            select(SessionReport)
            .where(
                SessionReport.status == "summarizing",
                or_(SessionReport.next_attempt_at.is_(None), SessionReport.next_attempt_at <= now),
                or_(SessionReport.claimed_until.is_(None), SessionReport.claimed_until < now),
            )
            .order_by(SessionReport.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if report is None:
            return None
        report.claimed_until = now + timedelta(seconds=get_config().codex_turn_timeout_seconds) + CLAIM_MARGIN
        db.commit()
        return report.id


# `type_rdv` in the agent's context (app/codex_agent/).
CONTEXT_KINDS = {"session": "seance", "discovery": "appel_decouverte", "meeting": "reunion"}


def session_context(db: Session, booking: Booking) -> dict:
    settings = get_settings(db)
    tz = settings.timezone
    common = {
        "type_rdv": CONTEXT_KINDS[booking.kind],
        "client": booking.customer.name,
        "date": f"{fmt.long_date(booking.start_datetime, tz)}, "
        f"{fmt.hour_range(booking.start_datetime, booking.end_datetime, tz, 'h')}",
        "consultant": settings.consultant_name,
        "langue": booking.client_locale,
    }
    if booking.kind == "discovery":
        return common | {"prestation": f"Appel découverte gratuit ({settings.discovery_duration_min} min)"}
    if booking.kind == "meeting":
        return common | {"titre": booking.title}
    purchase = booking.purchase
    number = db.scalar(
        select(func.count(Booking.id)).where(
            Booking.purchase_id == purchase.id,
            Booking.status == "completed",
            Booking.start_datetime <= booking.start_datetime,
        )
    )
    return common | {
        "prestation": purchase.product_name,
        "seance_numero": number,
        "heures_achetees": purchase.hours_purchased,
        "heures_restantes": purchase.hours_remaining,
        "derniere_seance": purchase.hours_remaining < 1,
    }


def _finish(report_id: int, now: datetime, apply: Callable[[Session, SessionReport], Email | None]) -> list[Email]:
    """Record the outcome of a claimed report, unless the admin took it over meanwhile."""
    with SessionLocal() as db:
        report = db.scalar(select(SessionReport).where(SessionReport.id == report_id).with_for_update())
        emails = []
        if report.status == "summarizing":
            email = apply(db, report)
            if email:
                emails.append(email)
        db.commit()
    return emails


def summarize(gw: Gateways, report_id: int, now: datetime) -> list[Email]:
    with SessionLocal() as db:
        report = db.get(SessionReport, report_id)
        context = session_context(db, report.booking)
        transcript_id, waiting_since = report.fireflies_transcript_id, report.waiting_since

    def failed(problem: str, action: str):
        def apply(db: Session, report: SessionReport) -> Email:
            report.status, report.error, report.claimed_until = "failed", problem, None
            return alert(db, report, problem, action)

        return apply

    def later(error: str):
        def apply(db: Session, report: SessionReport) -> None:
            report.claimed_until, report.error = None, error
            report.next_attempt_at = now + poll_interval()

        return apply

    try:
        sentences = gw.fireflies.sentences(transcript_id)
    except FirefliesError as e:
        if now - waiting_since >= max_wait():
            return _finish(report_id, now, failed(f"Transcription Fireflies illisible : {e}", RETRY_HINT))
        return _finish(report_id, now, later(str(e)))
    if not sentences:
        # Listed by Fireflies but still being processed.
        def not_ready(db: Session, report: SessionReport) -> None:
            report.status, report.claimed_until = "waiting_transcript", None
            report.next_attempt_at = now + poll_interval()

        return _finish(report_id, now, not_ready)

    lines = [f"{s.speaker} : {s.text}" for s in sentences]
    del sentences
    instructions = report_content.agent_instructions()
    problem = None
    output = png = None
    for attempt in range(1, MAX_SUMMARY_ATTEMPTS + 1):
        prompt = report_content.build_prompt(context, lines)
        if problem:
            prompt += f"\nTa réponse précédente a été refusée : {problem}. Respecte exactement le format demandé.\n"
        _count_attempt(report_id)
        try:
            output = report_content.parse_output(
                gw.codex.run_turn(instructions=instructions, prompt=prompt, output_schema=report_content.OUTPUT_SCHEMA)
            )
            png = report_content.render_png(output.image)
            break
        except CodexNotConnected:
            return _finish(
                report_id,
                now,
                failed("Codex n'est pas connecté.", "Connectez Codex dans l'admin, puis cliquez sur « Relancer »."),
            )
        except (report_content.InvalidOutput, CodexTurnFailed, CodexUnavailable) as e:
            problem = str(e)
            log.warning("report %s: summary attempt %d failed: %s", report_id, attempt, type(e).__name__)
    else:
        return _finish(report_id, now, failed(f"Résumé impossible : {problem}", RETRY_HINT))

    def ready(db: Session, report: SessionReport) -> None:
        report.summary = output.synthese.model_dump()
        report.image_png = png
        report.status, report.claimed_until, report.error = "ready", None, None

    return _finish(report_id, now, ready)


def _count_attempt(report_id: int) -> None:
    with SessionLocal() as db:
        db.execute(
            update(SessionReport)
            .where(SessionReport.id == report_id)
            .values(summary_attempts=SessionReport.summary_attempts + 1)
        )
        db.commit()


# --- step 3: draft -----------------------------------------------------------------------------------------------


def draft_ready(mailer: Mailer, now: datetime) -> None:
    emails = []
    with SessionLocal() as db:
        ready = db.scalars(
            select(SessionReport).where(SessionReport.status == "ready").with_for_update(skip_locked=True)
        ).all()
        for report in ready:
            if email := compose(db, report, now, with_summary=True):
                emails.append(email)
        db.commit()
    _send_all(mailer, emails)


def erase_expired(now: datetime) -> None:
    days = get_config().report_retention_days
    if days <= 0:
        return
    with SessionLocal() as db:
        db.execute(
            update(SessionReport)
            .where(
                SessionReport.erased_at.is_(None),
                SessionReport.status.in_(("drafted", "failed")),
                SessionReport.created_at < now - timedelta(days=days),
                or_(SessionReport.summary.is_not(None), SessionReport.image_png.is_not(None)),
            )
            .values(summary=None, image_png=None, erased_at=now)
        )
        db.commit()


def process(gw: Gateways, now: datetime) -> None:
    """One cycle. At most one summary per cycle: a Codex turn takes minutes, and the next report is claimed at the
    next cycle, with a fresh clock (a few sessions a day: a one-minute gap does not matter)."""
    erase_expired(now)
    poll_transcripts(gw, now)
    if (report_id := _claim(now)) is not None:
        _send_all(gw.mailer, summarize(gw, report_id, now))
    draft_ready(gw.mailer, now)


async def run_forever(gateways_factory: Callable[[], Gateways], interval_s: float, clock: Callable[[], datetime]) -> None:
    while True:
        try:
            await asyncio.to_thread(process, gateways_factory(), clock())
        except Exception:
            log.exception("session report job failed")
        await asyncio.sleep(interval_s)


# --- admin actions -----------------------------------------------------------------------------------------------


def _locked(db: Session, report_id: int) -> SessionReport:
    report = db.scalar(select(SessionReport).where(SessionReport.id == report_id).with_for_update())
    if report is None:
        raise ReportActionError("Compte rendu introuvable.", 404)
    return report


def _ensure_idle(report: SessionReport, now: datetime) -> None:
    if report.status in ("drafted", "ready"):
        raise ReportActionError("L'email de cette séance a déjà été préparé.")
    if report.status == "summarizing" and report.claimed_until is not None and report.claimed_until > now:
        raise ReportActionError("Le résumé est en cours de rédaction : réessayez dans quelques minutes.")


def retry(db: Session, report_id: int, now: datetime) -> SessionReport:
    """« Relancer » : summarize again if the transcript was found, otherwise look for it again for up to 6 h."""
    report = _locked(db, report_id)
    _ensure_idle(report, now)
    if report.fireflies_transcript_id:
        report.status = "summarizing"
    else:
        report.status, report.waiting_since = "waiting_transcript", now
    report.next_attempt_at, report.claimed_until, report.error = now, None, None
    db.commit()
    return report


def draft_without_summary(db: Session, report_id: int, now: datetime) -> Email | None:
    """« Créer le brouillon sans résumé » : the V1 email, always as a draft."""
    report = _locked(db, report_id)
    _ensure_idle(report, now)
    if report.booking.kind == "meeting":
        raise ReportActionError("Une réunion hors réservation n'a pas d'email sans compte rendu : relancez le résumé.")
    email = compose(db, report, now, with_summary=False, force_draft=True)
    db.commit()
    if email is None:
        raise ReportActionError(report.error, 409)
    return email


def retry_email(db: Session, report_id: int, now: datetime) -> Email | None:
    """« Recréer l'email » after a Gmail failure: the same email, prepared again with the current rules."""
    report = _locked(db, report_id)
    if report.status != "drafted" or report.delivery != "failed":
        raise ReportActionError("Cet email n'a pas échoué : rien à recréer.")
    report.error = None
    email = compose(db, report, now, with_summary=bool(report.with_summary))
    db.commit()
    if email is None:
        raise ReportActionError(report.error, 409)
    return email


def overview(db: Session, tz: ZoneInfo, limit: int = 30) -> list[dict]:
    """Finished sessions, newest first, with their report (None before the feature was on)."""
    rows = db.execute(
        select(Booking, SessionReport, SessionReport.image_png.is_not(None))
        .outerjoin(SessionReport, SessionReport.booking_id == Booking.id)
        # The PNGs are served one by one (reports/{id}/image.png), never loaded for the list.
        .options(joinedload(Booking.customer), joinedload(Booking.purchase), defer(SessionReport.image_png))
        .where(Booking.status == "completed")
        .order_by(Booking.start_datetime.desc())
        .limit(limit)
    ).all()
    wait = max_wait()

    def iso(value: datetime | None) -> str | None:
        return value.astimezone(tz).isoformat() if value else None

    return [
        {
            "booking_id": booking.id,
            "kind": booking.kind,
            "customer": booking.customer.name,
            "email": booking.customer.email,
            "product": product_label(booking),
            "start": iso(booking.start_datetime),
            "end": iso(booking.end_datetime),
            "report": None
            if report is None
            else {
                "id": report.id,
                "status": report.status,
                "transcript_found": report.fireflies_transcript_id is not None,
                "transcript_attempts": report.transcript_attempts,
                "summary_attempts": report.summary_attempts,
                "next_attempt_at": iso(report.next_attempt_at),
                "waiting_until": iso(report.waiting_since + wait),
                "error": report.error,
                "synthese": report.summary,
                "has_image": bool(has_image),
                "delivery": report.delivery,
                "with_summary": report.with_summary,
                "drafted_at": iso(report.drafted_at),
                "erased": report.erased_at is not None,
            },
        }
        for booking, report, has_image in rows
    ]
