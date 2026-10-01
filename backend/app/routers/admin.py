import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_config
from app.db import get_db
from app.deps import get_calendar, get_codex, get_mailer, get_now
from app.models import Booking, BookingToken, CodexLogin, Customer, Purchase, SessionReport
from app.schemas import (
    CancelBookingIn,
    CustomerPatchIn,
    LoginIn,
    ManualClientIn,
    ManualClientOut,
    PurchaseHoursIn,
    ReportSettingsIn,
)
from app.services import booking_service, calendar_print, codex_login, manual_purchase, notifications, session_reports
from app.services.calendar_service import CalendarUnavailable
from app.services.codex import CodexUnavailable
from app.services.settings_service import busy_calendar_ids, get_settings

router = APIRouter(prefix="/api/admin")

COOKIE = "iaf_admin"
SESSION_MAX_AGE = 12 * 3600


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().session_secret, salt="admin-session")


def require_admin(iaf_admin: str | None = Cookie(None)) -> None:
    if not iaf_admin:
        raise HTTPException(401, "Authentification requise.")
    try:
        _serializer().loads(iaf_admin, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise HTTPException(401, "Session expirée.")


@router.post("/login")
def login(body: LoginIn, response: Response):
    cfg = get_config()
    try:
        ok = bool(cfg.admin_password_hash) and PasswordHasher().verify(cfg.admin_password_hash, body.password)
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok:
        time.sleep(1)  # slow down guessing
        raise HTTPException(401, "Mot de passe incorrect.")
    response.set_cookie(
        COOKIE,
        _serializer().dumps({"admin": True}),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite="strict",
        path="/api/admin",
    )
    return {"status": "ok"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/api/admin")
    return {"status": "ok"}


@router.get("/overview", dependencies=[Depends(require_admin)])
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
                "product": b.purchase.product_name,
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
            "enabled": get_config().session_reports_enabled,
            "send_without_review": settings.send_reports_without_review,
            "sessions": session_reports.overview(db, tz),
        },
    }


@router.post("/clients", response_model=ManualClientOut, status_code=201, dependencies=[Depends(require_admin)])
def add_client(
    body: ManualClientIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    mailer=Depends(get_mailer),
):
    """A client paid outside the website: create the purchase and its booking link by hand."""
    created = manual_purchase.create(
        db,
        name=body.name,
        email=str(body.email).lower(),
        hours=body.hours,
        product_name=body.product_name,
        amount_cents=body.amount_cents,
    )
    if body.send_link:
        background.add_task(notifications.send_booking_link, mailer, created.purchase.id, created.token)
    return ManualClientOut(
        purchase_id=created.purchase.id,
        booking_url=notifications.booking_url(created.token, created.purchase.locale),
    )


@router.patch("/customers/{customer_id}", dependencies=[Depends(require_admin)])
def update_customer(customer_id: int, body: CustomerPatchIn, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Client introuvable.")
    customer.auto_send_next_link = body.auto_send_next_link
    db.commit()
    return {"customer_id": customer.id, "auto_send_next_link": customer.auto_send_next_link}


@router.post("/bookings/{booking_id}/cancel", dependencies=[Depends(require_admin)])
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
    return {"status": "cancelled", **booking_service.hours_summary(booking.purchase)}


@router.patch("/purchases/{purchase_id}", dependencies=[Depends(require_admin)])
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


@router.get("/calendar.pdf", dependencies=[Depends(require_admin)])
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


@router.get("/reports/{report_id}/image.png", dependencies=[Depends(require_admin)])
def report_image(report_id: int, db: Session = Depends(get_db)):
    png = db.scalar(select(SessionReport.image_png).where(SessionReport.id == report_id))
    if png is None:
        raise HTTPException(404, "Pas d'infographie pour ce compte rendu.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/reports/{report_id}/retry", dependencies=[Depends(require_admin)])
def retry_report(report_id: int, db: Session = Depends(get_db), now: datetime = Depends(get_now)):
    """« Relancer » : the Fireflies search (6 h more), or the summary if the transcript was found."""
    report = _report_action(lambda: session_reports.retry(db, report_id, now))
    return {"id": report.id, "status": report.status}


@router.post("/reports/{report_id}/draft-without-summary", dependencies=[Depends(require_admin)])
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


@router.patch("/report-settings", dependencies=[Depends(require_admin)])
def update_report_settings(body: ReportSettingsIn, db: Session = Depends(get_db)):
    """« Envoyer aussi les résumés sans relecture » for the clients on « Envoi auto »."""
    settings = get_settings(db)
    settings.send_reports_without_review = body.send_without_review
    db.commit()
    return {"send_without_review": settings.send_reports_without_review}


# --- Codex connection (device authorization) -------------------------------------------------------------------


def _codex_call(action):
    try:
        return action()
    except CodexUnavailable as e:
        raise HTTPException(502, f"Le service Codex est injoignable : {e}")


def _login(db: Session, login_id: int) -> CodexLogin:
    login = db.scalar(select(CodexLogin).where(CodexLogin.id == login_id).with_for_update())
    if login is None:
        raise HTTPException(404, "Connexion introuvable.")
    return login


@router.get("/codex", dependencies=[Depends(require_admin)])
def codex_status(db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)):
    """connected / expired / disconnected / unavailable. Never any token: they stay in the codex container."""
    if not get_config().session_reports_enabled:
        return {"state": "not_configured", "email": None, "plan": None, "detail": None, "pending_login": None}
    return codex_login.status(db, codex, now)


@router.post("/codex/login", status_code=201, dependencies=[Depends(require_admin)])
def codex_start_login(db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)):
    """« Connecter Codex » : device code to type on https://auth.openai.com/codex/device."""
    return codex_login.login_dict(_codex_call(lambda: codex_login.start(db, codex, now)))


@router.get("/codex/login/{login_id}", dependencies=[Depends(require_admin)])
def codex_login_status(
    login_id: int, db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)
):
    return codex_login.login_dict(codex_login.refresh(db, codex, _login(db, login_id), now))


@router.post("/codex/login/{login_id}/cancel", dependencies=[Depends(require_admin)])
def codex_cancel_login(
    login_id: int, db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)
):
    return codex_login.login_dict(codex_login.cancel(db, codex, _login(db, login_id), now))


@router.post("/codex/logout", dependencies=[Depends(require_admin)])
def codex_logout(db: Session = Depends(get_db), codex=Depends(get_codex), now: datetime = Depends(get_now)):
    _codex_call(lambda: codex_login.logout(db, codex, now))
    return {"state": "disconnected"}
