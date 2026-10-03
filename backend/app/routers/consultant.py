"""Consultant cockpit (/consultant): learners, sessions, reports, action plans, company profiles, NDA.

Google sign-in only, with the consultant role (app.auth). The configuration (Codex, Fireflies, staff accounts,
reminder delays) is the admin's: app.routers.admin.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import Staff, require_consultant
from app.config import get_config
from app.db import get_db
from app.deps import get_calendar, get_codex, get_company_register, get_fireflies, get_mailer, get_now
from app.models import ActionPlan, Booking, BookingToken, Customer, NdaDocument, Purchase, SessionReport
from app.schemas import (
    CancelBookingIn,
    CompanyAttachIn,
    CustomerPatchIn,
    LearnerPatchIn,
    ManualClientIn,
    ManualClientOut,
    MeetingReportIn,
    NdaSendIn,
    NdaSignedIn,
    PlanMessageIn,
    PlanValidateIn,
    PurchaseHoursIn,
    ReportSettingsIn,
)
from app.services import (
    action_plans,
    booking_service,
    calendar_print,
    company,
    learners,
    manual_purchase,
    meetings,
    nda,
    notifications,
    research,
    session_reports,
)
from app.services.calendar_service import CalendarUnavailable
from app.services.fireflies import FirefliesError
from app.services.settings_service import busy_calendar_ids, get_settings

router = APIRouter(prefix="/api/consultant")


@router.get("/me")
def me(staff: Staff = Depends(require_consultant)):
    return {"id": staff.id, "email": staff.email, "name": staff.name}


@router.get("/overview", dependencies=[Depends(require_consultant)])
def overview(db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    settings = get_settings(db)
    tz = ZoneInfo(settings.timezone)
    local_now = now.astimezone(tz)
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    paid = Purchase.payment_status == "paid"
    month_count, month_amount = db.execute(
        select(func.count(Purchase.id), func.coalesce(func.sum(Purchase.amount_cents), 0)).where(
            paid, Purchase.created_at >= month_start
        )
    ).one()
    hours_sold, hours_booked = db.execute(
        select(func.coalesce(func.sum(Purchase.hours_purchased), 0), func.coalesce(func.sum(Purchase.hours_booked), 0)).where(paid)
    ).one()
    done_seconds = db.scalar(
        select(func.coalesce(func.sum(func.extract("epoch", Booking.end_datetime - Booking.start_datetime)), 0))
        .join(Purchase)
        .where(Booking.status.in_(("confirmed", "completed")), Booking.end_datetime <= now, paid)
    )
    hours_done = float(done_seconds) / 3600

    upcoming = db.scalars(
        select(Booking)
        .options(selectinload(Booking.customer), selectinload(Booking.purchase))
        .where(Booking.status == "confirmed", Booking.start_datetime >= now)
        .order_by(Booking.start_datetime)
        .limit(20)
    ).all()

    purchases = db.scalars(
        select(Purchase)
        .options(selectinload(Purchase.customer), selectinload(Purchase.bookings))
        .order_by(Purchase.created_at.desc())
        .limit(200)
    ).all()

    # Newest active token per purchase, so the admin can copy a client's booking link.
    tokens = dict(
        db.execute(
            select(BookingToken.purchase_id, BookingToken.token)
            .where(BookingToken.revoked_at.is_(None), BookingToken.purchase_id.in_([p.id for p in purchases]))
            .order_by(BookingToken.id)
        ).all()
    )

    def booking_dict(b: Booking) -> dict:
        return {
            "start": b.start_datetime.astimezone(tz).isoformat(),
            "end": b.end_datetime.astimezone(tz).isoformat(),
            "meet_url": b.meet_url,
        }

    return {
        "kpis": {
            "payments_this_month": month_count,
            "revenue_this_month_cents": int(month_amount),
            "hours_sold": int(hours_sold),
            "hours_booked": int(hours_booked),
            "hours_done": hours_done,
            "hours_to_schedule": int(hours_sold) - int(hours_booked),
            "hours_to_deliver": int(hours_sold) - hours_done,
        },
        "upcoming": [
            {
                "booking_id": b.id,
                "customer": b.customer.name,
                "email": b.customer.email,
                "kind": b.kind,
                "product": session_reports.product_label(b),
                **booking_dict(b),
            }
            for b in upcoming
        ],
        "clients": [
            {
                "purchase_id": p.id,
                "customer_id": p.customer_id,
                "name": p.customer.name,
                "email": p.customer.email,
                "product": p.product_name,
                "hours_purchased": p.hours_purchased,
                "hours_booked": p.hours_booked,
                "hours_remaining": p.hours_remaining,
                "payment_status": p.payment_status,
                "manual": p.product_id == manual_purchase.MANUAL_PRODUCT_ID,
                "auto_send_next_link": p.customer.auto_send_next_link,
                "booking_url": notifications.booking_url(tokens[p.id], p.locale) if p.id in tokens else None,
                "created_at": p.created_at.astimezone(tz).isoformat(),
                "booking": next((booking_dict(b) for b in p.bookings if b.status == "confirmed"), None),
            }
            for p in purchases
        ],
        "reports": {
            "enabled": session_reports.enabled(db),
            "send_without_review": settings.send_reports_without_review,
            "sessions": session_reports.overview(db, tz),
        },
    }


@router.post("/clients", response_model=ManualClientOut, status_code=201, dependencies=[Depends(require_consultant)])
def add_client(
    body: ManualClientIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    mailer=Depends(get_mailer),
):
    """A client met outside the website (WhatsApp, a recommendation…). With hours paid outside the website, the
    purchase and its booking link are created too; without, the client is only added to the follow-up."""
    created = manual_purchase.create(
        db,
        name=body.name,
        email=str(body.email).lower(),
        acquisition_source=body.acquisition_source,
        acquisition_detail=body.acquisition_detail,
        hours=body.hours,
        product_name=body.product_name or "Conseil IA",
        amount_cents=body.amount_cents,
    )
    if created.purchase is None:
        return ManualClientOut(customer_id=created.customer.id, purchase_id=None, booking_url=None)
    if body.send_link:
        background.add_task(notifications.send_booking_link, mailer, created.purchase.id, created.token)
    return ManualClientOut(
        customer_id=created.customer.id,
        purchase_id=created.purchase.id,
        booking_url=notifications.booking_url(created.token, created.purchase.locale),
    )


@router.patch("/customers/{customer_id}", dependencies=[Depends(require_consultant)])
def update_customer(customer_id: int, body: CustomerPatchIn, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Client introuvable.")
    customer.auto_send_next_link = body.auto_send_next_link
    db.commit()
    return {"customer_id": customer.id, "auto_send_next_link": customer.auto_send_next_link}


@router.post("/bookings/{booking_id}/cancel", dependencies=[Depends(require_consultant)])
def cancel_booking(
    booking_id: int,
    body: CancelBookingIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    calendar=Depends(get_calendar),
    mailer=Depends(get_mailer),
    now: datetime = Depends(get_now),
):
    """Session moved or cancelled: the Google event is deleted and the hour goes back to the client."""
    booking = booking_service.cancel(db, calendar, booking_id, now)
    if body.notify:
        background.add_task(notifications.send_booking_cancelled, mailer, booking.id)
    hours = booking_service.hours_summary(booking.purchase) if booking.purchase else {}
    return {"status": "cancelled", **hours}


@router.patch("/purchases/{purchase_id}", dependencies=[Depends(require_consultant)])
def update_purchase_hours(purchase_id: int, body: PurchaseHoursIn, db: Session = Depends(get_db)):
    """Adjust the hours of a purchase (partial refund, extra hours paid outside the website)."""
    purchase = db.scalar(select(Purchase).where(Purchase.id == purchase_id).with_for_update())
    if purchase is None:
        raise HTTPException(404, "Achat introuvable.")
    if body.hours_purchased < purchase.hours_booked:
        db.rollback()
        raise HTTPException(
            422, f"Impossible : {purchase.hours_booked} h sont déjà réservées ou réalisées pour ce client."
        )
    purchase.hours_purchased = body.hours_purchased
    db.commit()
    return booking_service.hours_summary(purchase)


@router.get("/calendar.pdf", dependencies=[Depends(require_consultant)])
def calendar_pdf(
    start: date,
    end: date,
    db: Session = Depends(get_db),
    calendar=Depends(get_calendar),
    now: datetime = Depends(get_now),
):
    """« Imprimer mon calendrier » : every calendar, each busy period printed as « Occupé », from `start` to `end`."""
    if end < start:
        raise HTTPException(422, "La date de fin doit être le même jour ou après la date de début.")
    if (end - start).days >= calendar_print.MAX_DAYS:
        raise HTTPException(422, f"Période trop longue : {calendar_print.MAX_DAYS} jours au plus.")
    settings = get_settings(db)
    tz = ZoneInfo(settings.timezone)
    try:
        pdf = calendar_print.build_pdf(calendar, busy_calendar_ids(db, settings), start, end, tz, now)
    except CalendarUnavailable:
        raise HTTPException(502, "Un agenda Google ne répond pas. Réessayez dans un instant.")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="calendrier-{start}-au-{end}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


# --- session reports -------------------------------------------------------------------------------------------


def _report_action(action):
    try:
        return action()
    except session_reports.ReportActionError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/reports/{report_id}/image.png", dependencies=[Depends(require_consultant)])
def report_image(report_id: int, db: Session = Depends(get_db)):
    png = db.scalar(select(SessionReport.image_png).where(SessionReport.id == report_id))
    if png is None:
        raise HTTPException(404, "Pas d'infographie pour ce compte rendu.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/reports/{report_id}/retry", dependencies=[Depends(require_consultant)])
def retry_report(report_id: int, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    """« Relancer » : the Fireflies search (6 h more), or the summary if the transcript was found."""
    report = _report_action(lambda: session_reports.retry(db, report_id, now))
    return {"id": report.id, "status": report.status}


@router.post("/reports/{report_id}/draft-without-summary", dependencies=[Depends(require_consultant)])
def draft_without_summary(
    report_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    mailer=Depends(get_mailer),
    now: datetime = Depends(get_now),
):
    email = _report_action(lambda: session_reports.draft_without_summary(db, report_id, now))
    background.add_task(session_reports.deliver, mailer, email)
    return {"id": report_id, "status": "drafted"}


@router.post("/reports/{report_id}/retry-email", dependencies=[Depends(require_consultant)])
def retry_report_email(
    report_id: int,
    db: Session = Depends(get_db),
    mailer=Depends(get_mailer),
    now: datetime = Depends(get_now),
):
    """« Recréer le brouillon » : Gmail refused the draft (or the email) of this report. Gmail is called before
    answering, so the admin sees at once whether this attempt failed too."""
    email = _report_action(lambda: session_reports.retry_email(db, report_id, now))
    if not session_reports.deliver(mailer, email):
        raise HTTPException(502, session_reports.GMAIL_FAILED)
    return {"id": report_id, "status": "drafted"}


@router.get("/meetings", dependencies=[Depends(require_consultant)])
def list_meetings(db: Session = Depends(get_db), fireflies=Depends(get_fireflies), now: datetime = Depends(get_now)):
    """« Autres réunions » : Fireflies recordings of the last 7 days, to summarize a meeting booked elsewhere."""
    if not session_reports.enabled(db):
        raise HTTPException(409, "Connectez d'abord Fireflies et Codex.")
    try:
        return {"meetings": meetings.recent(db, fireflies, now, ZoneInfo(get_settings(db).timezone))}
    except FirefliesError as e:
        raise HTTPException(502, f"Fireflies ne répond pas : {e}.")


@router.post("/meetings", status_code=201, dependencies=[Depends(require_consultant)])
def create_meeting_report(body: MeetingReportIn, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    """Summarize that recording for that person: the report is written within minutes, then left as a Gmail draft."""
    if not session_reports.enabled(db):
        raise HTTPException(409, "Connectez d'abord Fireflies et Codex.")
    try:
        report = meetings.create_report(
            db,
            transcript_id=body.transcript_id,
            title=body.title or None,
            start=body.start,
            end=body.end,
            name=body.name,
            email=str(body.email).lower(),
            locale=body.locale,
            now=now,
        )
    except meetings.MeetingError as e:
        raise HTTPException(e.status_code, e.message)
    return {"report_id": report.id, "booking_id": report.booking_id}


# --- confidentiality agreement (NDA) ---------------------------------------------------------------------------


def _nda_action(action):
    try:
        return action()
    except nda.NdaError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/nda", dependencies=[Depends(require_consultant)])
def nda_overview(db: Session = Depends(get_db)):
    """The uploaded PDFs, and every person the agreement was sent to (returned signed or not)."""
    return nda.overview(db, ZoneInfo(get_settings(db).timezone))


@router.put("/nda/documents/{locale}", dependencies=[Depends(require_consultant)])
async def nda_upload(
    locale: str,
    request: Request,
    filename: str | None = None,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
):
    """The PDF already signed by the consultant, sent as the raw request body (application/pdf)."""
    pdf = await request.body()
    doc = _nda_action(lambda: nda.upload(db, locale, filename, pdf, now))
    return {"locale": doc.locale, "filename": doc.filename, "size": len(doc.pdf)}


@router.get("/nda/documents/{locale}.pdf", dependencies=[Depends(require_consultant)])
def nda_download(locale: str, db: Session = Depends(get_db)):
    doc = db.get(NdaDocument, locale)
    if doc is None:
        raise HTTPException(404, "Aucun PDF pour cette langue.")
    return Response(
        doc.pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"', "Cache-Control": "private, no-store"},
    )


@router.delete("/nda/documents/{locale}", dependencies=[Depends(require_consultant)])
def nda_delete(locale: str, db: Session = Depends(get_db)):
    _nda_action(lambda: nda.remove(db, locale))
    return {"status": "deleted"}


@router.post("/nda/send", dependencies=[Depends(require_consultant)])
def nda_send(body: NdaSendIn, db: Session = Depends(get_db), mailer=Depends(get_mailer), now: datetime = Depends(get_now)):
    """« Envoyer le NDA » (or send it again) to a client or a contact met elsewhere."""
    customer = _nda_action(
        lambda: nda.send_now(db, mailer, name=body.name, email=str(body.email).lower(), locale=body.locale, now=now)
    )
    return {"customer_id": customer.id, "sent_at": customer.nda_sent_at.isoformat()}


@router.patch("/customers/{customer_id}/nda", dependencies=[Depends(require_consultant)])
def nda_signed(customer_id: int, body: NdaSignedIn, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    """« Signé reçu » : the customer returned the agreement signed (by replying to its email)."""
    customer = _nda_action(lambda: nda.set_signed(db, customer_id, body.signed, now))
    return {"customer_id": customer.id, "signed_at": customer.nda_signed_at.isoformat() if customer.nda_signed_at else None}


@router.patch("/report-settings", dependencies=[Depends(require_consultant)])
def update_report_settings(body: ReportSettingsIn, db: Session = Depends(get_db)):
    """« Envoyer aussi les résumés sans relecture » for the clients on « Envoi auto »."""
    settings = get_settings(db)
    settings.send_reports_without_review = body.send_without_review
    db.commit()
    return {"send_without_review": settings.send_reports_without_review}


# --- learners (V3 cockpit) -------------------------------------------------------------------------------------


def _learner(db: Session, staff: Staff, customer_id: int) -> Customer:
    customer = learners.get_customer(db, staff, customer_id)
    if customer is None:
        raise HTTPException(404, "Apprenant introuvable.")
    return customer


@router.get("/learners")
def list_learners(
    hidden: bool = False,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    now: datetime = Depends(get_now),
):
    """Every learner with the sessions left, the next one, the pace and what needs attention. Learners idle for
    `hide_after_days` are left out unless `hidden`."""
    return learners.rows(db, staff, now, include_hidden=hidden)


@router.get("/learners/{customer_id}")
def learner_detail(
    customer_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_consultant), now: datetime = Depends(get_now)
):
    return learners.detail(db, _learner(db, staff, customer_id), now)


@router.patch("/learners/{customer_id}")
def update_learner(
    customer_id: int, body: LearnerPatchIn, db: Session = Depends(get_db), staff: Staff = Depends(require_consultant)
):
    """Company name, acquisition and private notes of the consultant."""
    customer = _learner(db, staff, customer_id)
    for field in body.model_fields_set:
        setattr(customer, field, getattr(body, field) or None)
    db.commit()
    return {
        "customer_id": customer.id,
        "company_name": customer.company_name,
        "notes": customer.notes,
        "acquisition_source": customer.acquisition_source,
        "acquisition_detail": customer.acquisition_detail,
    }


def _company_call(action):
    try:
        return action()
    except company.CompanyError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/learners/{customer_id}/company/search")
def company_search(
    customer_id: int,
    q: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    register=Depends(get_company_register),
    now: datetime = Depends(get_now),
):
    """Candidates from the official register; without `q`, searched from the company name or the email domain."""
    customer = _learner(db, staff, customer_id)
    query = q if q is not None else company.suggested_query(customer)
    if not query.strip():
        return {"query": "", "results": []}
    return {"query": query, "results": _company_call(lambda: company.search(register, query, now.date()))}


@router.put("/learners/{customer_id}/company")
def company_attach(
    customer_id: int,
    body: CompanyAttachIn,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    register=Depends(get_company_register),
    now: datetime = Depends(get_now),
):
    customer = _learner(db, staff, customer_id)
    return _company_call(lambda: company.attach(db, register, customer, body.siren, now))


@router.delete("/learners/{customer_id}/company")
def company_detach(customer_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_consultant)):
    company.detach(db, _learner(db, staff, customer_id))
    return {"status": "detached"}


def _codex_ready() -> None:
    if not get_config().codex_enabled:
        raise HTTPException(409, "Codex n'est pas configuré sur ce serveur.")


@router.post("/learners/{customer_id}/research", status_code=202)
def start_research(
    customer_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    codex=Depends(get_codex),
    now: datetime = Depends(get_now),
):
    """Web research by Codex (a few minutes): poll the learner until `research.status` is no longer running."""
    _codex_ready()
    customer = _learner(db, staff, customer_id)
    try:
        research.start(db, customer, now)
    except research.ResearchError as e:
        raise HTTPException(e.status_code, e.message)
    background.add_task(research.run, codex, customer.id, now)
    return {"status": "running"}


def _plan_call(action):
    try:
        return action()
    except action_plans.PlanError as e:
        raise HTTPException(e.status_code, e.message)


@router.post("/learners/{customer_id}/plan", status_code=202)
def generate_plan(
    customer_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    codex=Depends(get_codex),
    now: datetime = Depends(get_now),
):
    """« Générer le plan », or « Régénérer » (a full rewrite from the updated dossier, the chat is kept)."""
    _codex_ready()
    customer = _learner(db, staff, customer_id)
    exists = db.scalar(select(ActionPlan.id).where(ActionPlan.customer_id == customer.id)) is not None
    plan = _plan_call(
        lambda: action_plans.request(db, customer, staff.id, now, action_plans.REWRITE_REQUEST if exists else None)
    )
    background.add_task(action_plans.run_now, codex, plan.id, lambda: now)
    return {"status": plan.status}


@router.post("/learners/{customer_id}/plan/messages", status_code=202)
def plan_message(
    customer_id: int,
    body: PlanMessageIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    codex=Depends(get_codex),
    now: datetime = Depends(get_now),
):
    """Chat with the plan agent: the answer and the updated plan come with the next polls of the learner."""
    _codex_ready()
    customer = _learner(db, staff, customer_id)
    plan = _plan_call(lambda: action_plans.request(db, customer, staff.id, now, body.message))
    background.add_task(action_plans.run_now, codex, plan.id, lambda: now)
    return {"status": plan.status}


@router.patch("/learners/{customer_id}/plan")
def validate_plan(
    customer_id: int,
    body: PlanValidateIn,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_consultant),
    now: datetime = Depends(get_now),
):
    plan = _plan_call(lambda: action_plans.validate(db, _learner(db, staff, customer_id), body.validated, now))
    return {"validated_at": plan.validated_at.isoformat() if plan.validated_at else None}
