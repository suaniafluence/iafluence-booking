import time
from datetime import datetime
from zoneinfo import ZoneInfo

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_config
from app.db import get_db
from app.deps import get_mailer, get_now
from app.models import Booking, BookingToken, Customer, Purchase
from app.schemas import CustomerPatchIn, LoginIn, ManualClientIn, ManualClientOut
from app.services import manual_purchase, notifications
from app.services.settings_service import get_settings

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
            {"customer": b.customer.name, "email": b.customer.email, "product": b.purchase.product_name, **booking_dict(b)}
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
                "booking_url": notifications.booking_url(tokens[p.id]) if p.id in tokens else None,
                "created_at": p.created_at.astimezone(tz).isoformat(),
                "booking": next((booking_dict(b) for b in p.bookings if b.status == "confirmed"), None),
            }
            for p in purchases
        ],
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
        name=body.name.strip(),
        email=str(body.email).lower(),
        hours=body.hours,
        product_name=body.product_name.strip(),
        amount_cents=body.amount_cents,
    )
    if body.send_link:
        background.add_task(notifications.send_booking_link, mailer, created.purchase.id, created.token)
    return ManualClientOut(purchase_id=created.purchase.id, booking_url=notifications.booking_url(created.token))


@router.patch("/customers/{customer_id}", dependencies=[Depends(require_admin)])
def update_customer(customer_id: int, body: CustomerPatchIn, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, "Client introuvable.")
    customer.auto_send_next_link = body.auto_send_next_link
    db.commit()
    return {"customer_id": customer.id, "auto_send_next_link": customer.auto_send_next_link}
