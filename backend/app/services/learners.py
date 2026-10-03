"""The consultant's cockpit: one row per learner (customer) with where they stand and what to do next.

Time management: a session books 1 hour, so the hours left are the sessions left. For each learner:
- hours bought, done (completed sessions), booked ahead, still to schedule;
- the pace so far (days between sessions) and the date the programme would end at that pace;
- inactivity: days since the last session (or purchase, or call). After `reminder_after_days` the reminder job
  writes to them (app.services.reminders); after `hide_after_days` they leave the list — and come back by
  themselves on their next booking or purchase, or when the consultant shows the hidden ones.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import Staff
from app.models import ActionPlan, Booking, Customer, CustomerProfile, Purchase, SessionReport, Settings
from app.services import notifications, session_reports
from app.services.settings_service import get_settings

# A paid learner with hours to schedule and no session for this long is flagged.
IDLE_ALERT_DAYS = 10


@dataclass
class Activity:
    paid: list[Purchase]
    hours_purchased: int
    hours_booked: int
    hours_to_schedule: int
    sessions_done: int
    sessions_to_deliver: int
    upcoming: Booking | None
    last_session: Booking | None
    last_activity: datetime | None
    idle_days: int | None
    status: str  # prospect | en_cours | termine | rembourse
    pace_days: float | None
    projected_end: datetime | None


def scoped(stmt, staff: Staff):
    """A consultant sees their customers and the ones nobody follows yet (one consultant today)."""
    return stmt.where(or_(Customer.consultant_id == staff.id, Customer.consultant_id.is_(None)))


def activity(customer: Customer, bookings: list[Booking], now: datetime) -> Activity:
    paid = [p for p in customer.purchases if p.payment_status == "paid"]
    refunded = [p for p in customer.purchases if p.payment_status != "paid"]
    live = [b for b in bookings if b.status != "cancelled"]
    sessions = sorted(
        (b for b in live if b.kind == "session" and b.status == "completed" and b.purchase in paid),
        key=lambda b: b.start_datetime,
    )
    upcoming = min(
        (b for b in live if b.status == "confirmed" and b.end_datetime > now), key=lambda b: b.start_datetime, default=None
    )
    finished = [b for b in live if b.status == "completed"]
    last_session = max(finished, key=lambda b: b.end_datetime, default=None)

    hours_purchased = sum(p.hours_purchased for p in paid)
    hours_booked = sum(p.hours_booked for p in paid)
    to_deliver = hours_purchased - len(sessions)
    moments = [b.end_datetime for b in finished] + [p.created_at for p in customer.purchases]
    if not moments and customer.created_at:
        moments.append(customer.created_at)
    last_activity = max(moments, default=None)
    idle_days = None if upcoming or last_activity is None else max(0, (now - last_activity).days)

    if paid:
        status = "en_cours" if to_deliver > 0 else "termine"
    else:
        status = "rembourse" if refunded else "prospect"

    pace = projected = None
    if len(sessions) >= 2:
        span = sessions[-1].start_datetime - sessions[0].start_datetime
        pace = span.total_seconds() / 86400 / (len(sessions) - 1)
    if pace and to_deliver > 0:
        projected = max(now, sessions[-1].start_datetime) + timedelta(days=pace * to_deliver)

    return Activity(
        paid=paid,
        hours_purchased=hours_purchased,
        hours_booked=hours_booked,
        hours_to_schedule=hours_purchased - hours_booked,
        sessions_done=len(sessions),
        sessions_to_deliver=max(0, to_deliver),
        upcoming=upcoming,
        last_session=last_session,
        last_activity=last_activity,
        idle_days=idle_days,
        status=status,
        pace_days=round(pace, 1) if pace else None,
        projected_end=projected,
    )


def is_hidden(act: Activity, settings: Settings) -> bool:
    return act.idle_days is not None and act.idle_days >= settings.hide_after_days


def alerts(customer: Customer, act: Activity, plan: ActionPlan | None, settings: Settings) -> list[dict]:
    out = []
    if act.status == "en_cours" and act.upcoming is None and act.hours_to_schedule > 0:
        if act.idle_days is not None and act.idle_days >= IDLE_ALERT_DAYS:
            out.append({"niveau": "attention", "texte": f"Aucune séance prévue depuis {act.idle_days} jours"})
        else:
            out.append({"niveau": "info", "texte": "Prochaine séance pas encore réservée"})
    if act.status == "en_cours" and plan is None:
        out.append({"niveau": "info", "texte": "Pas encore de plan d'action"})
    if plan is not None and plan.status == "failed":
        out.append({"niveau": "attention", "texte": "Le plan d'action n'a pas pu être rédigé"})
    if customer.nda_sent_at and not customer.nda_signed_at:
        out.append({"niveau": "info", "texte": "NDA envoyé, pas encore reçu signé"})
    if act.idle_days is not None and act.idle_days >= settings.reminder_after_days and act.status != "rembourse":
        if customer.reminder_sent_at and act.last_activity and customer.reminder_sent_at >= act.last_activity:
            out.append({"niveau": "info", "texte": "Relancé, sans réponse pour l'instant"})
    return out


def _iso(value: datetime | None, tz: ZoneInfo) -> str | None:
    return value.astimezone(tz).isoformat() if value else None


def _booking_short(b: Booking | None, tz: ZoneInfo) -> dict | None:
    if b is None:
        return None
    return {"id": b.id, "kind": b.kind, "start": _iso(b.start_datetime, tz), "end": _iso(b.end_datetime, tz), "meet_url": b.meet_url}


def _load(db: Session, stmt) -> tuple[list[Customer], dict[int, list[Booking]]]:
    customers = db.scalars(stmt.options(selectinload(Customer.purchases))).all()
    ids = [c.id for c in customers]
    bookings: dict[int, list[Booking]] = {cid: [] for cid in ids}
    if ids:
        for b in db.scalars(
            select(Booking).options(selectinload(Booking.purchase)).where(Booking.customer_id.in_(ids))
        ):
            bookings[b.customer_id].append(b)
    return customers, bookings


def rows(db: Session, staff: Staff, now: datetime, include_hidden: bool = False) -> dict:
    settings = get_settings(db)
    tz = ZoneInfo(settings.timezone)
    customers, bookings = _load(db, scoped(select(Customer), staff))
    plans = {p.customer_id: p for p in db.scalars(select(ActionPlan).where(ActionPlan.customer_id.in_([c.id for c in customers])))}
    out, hidden = [], 0
    for customer in customers:
        act = activity(customer, bookings[customer.id], now)
        if is_hidden(act, settings):
            hidden += 1
            if not include_hidden:
                continue
        plan = plans.get(customer.id)
        out.append(
            {
                "customer_id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "company": customer.company_name,
                "status": act.status,
                "hours_purchased": act.hours_purchased,
                "sessions_done": act.sessions_done,
                "sessions_to_deliver": act.sessions_to_deliver,
                "hours_to_schedule": act.hours_to_schedule,
                "next_session": _booking_short(act.upcoming, tz),
                "last_session": _booking_short(act.last_session, tz),
                "idle_days": act.idle_days,
                "hidden": is_hidden(act, settings),
                "pace_days": act.pace_days,
                "projected_end": _iso(act.projected_end, tz),
                "plan_status": plan.status if plan else None,
                "reminder_sent_at": _iso(customer.reminder_sent_at, tz),
                "alerts": alerts(customer, act, plan, settings),
            }
        )
    # Next session first, then the ones that need attention, then the least recently active.
    order = {"en_cours": 0, "prospect": 1, "termine": 2, "rembourse": 3}
    out.sort(
        key=lambda r: (
            r["next_session"] is None,
            r["next_session"]["start"] if r["next_session"] else "",
            order[r["status"]],
            -(r["idle_days"] or 0),
        )
    )
    return {
        "learners": out,
        "hidden_count": hidden,
        "settings": {
            "reminder_after_days": settings.reminder_after_days,
            "hide_after_days": settings.hide_after_days,
            "session_duration_min": settings.booking_duration_min,
        },
    }


def get_customer(db: Session, staff: Staff, customer_id: int) -> Customer | None:
    return db.scalar(scoped(select(Customer).where(Customer.id == customer_id), staff))


def timeline(db: Session, customer_id: int, tz: ZoneInfo) -> list[dict]:
    """Every call and session, newest first, with its summary while it is kept."""
    rows_ = db.execute(
        select(Booking, SessionReport)
        .outerjoin(SessionReport, SessionReport.booking_id == Booking.id)
        .options(selectinload(Booking.purchase))
        .where(Booking.customer_id == customer_id)
        .order_by(Booking.start_datetime.desc())
    ).all()
    return [
        {
            "booking_id": b.id,
            "kind": b.kind,
            "status": b.status,
            "label": session_reports.product_label(b),
            "start": _iso(b.start_datetime, tz),
            "end": _iso(b.end_datetime, tz),
            "meet_url": b.meet_url,
            "message": b.message,
            "report": None
            if r is None
            else {"id": r.id, "status": r.status, "synthese": r.summary, "erased": r.erased_at is not None},
        }
        for b, r in rows_
    ]


def detail(db: Session, customer: Customer, now: datetime) -> dict:
    settings = get_settings(db)
    tz = ZoneInfo(settings.timezone)
    _, bookings = _load(db, select(Customer).where(Customer.id == customer.id))
    act = activity(customer, bookings[customer.id], now)
    profile = db.get(CustomerProfile, customer.id)
    plan = db.scalar(select(ActionPlan).where(ActionPlan.customer_id == customer.id))
    purchases = sorted(customer.purchases, key=lambda p: p.created_at, reverse=True)
    from app.services import action_plans  # circular: action_plans builds its dossier from this module

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "company_name": customer.company_name,
            "siren": customer.siren,
            "notes": customer.notes,
            "acquisition_source": customer.acquisition_source,
            "acquisition_detail": customer.acquisition_detail,
            "auto_send_next_link": customer.auto_send_next_link,
            "nda_sent_at": _iso(customer.nda_sent_at, tz),
            "nda_signed_at": _iso(customer.nda_signed_at, tz),
            "reminder_sent_at": _iso(customer.reminder_sent_at, tz),
            "created_at": _iso(customer.created_at, tz),
        },
        "time": {
            "status": act.status,
            "hours_purchased": act.hours_purchased,
            "hours_booked": act.hours_booked,
            "hours_to_schedule": act.hours_to_schedule,
            "sessions_done": act.sessions_done,
            "sessions_to_deliver": act.sessions_to_deliver,
            "session_duration_min": settings.booking_duration_min,
            "next_session": _booking_short(act.upcoming, tz),
            "idle_days": act.idle_days,
            "pace_days": act.pace_days,
            "projected_end": _iso(act.projected_end, tz),
            "hidden": is_hidden(act, settings),
            "alerts": alerts(customer, act, plan, settings),
        },
        "purchases": [
            {
                "id": p.id,
                "product": p.product_name,
                "hours_purchased": p.hours_purchased,
                "hours_booked": p.hours_booked,
                "hours_remaining": p.hours_remaining,
                "payment_status": p.payment_status,
                "amount_cents": p.amount_cents,
                "created_at": _iso(p.created_at, tz),
                "booking_url": notifications.booking_url(token, p.locale)
                if (token := notifications.active_token(db, p.id)) and p.payment_status == "paid"
                else None,
            }
            for p in purchases
        ],
        "timeline": timeline(db, customer.id, tz),
        "company": profile.company if profile else None,
        "company_fetched_at": _iso(profile.company_fetched_at, tz) if profile else None,
        "research": {
            "status": profile.research_status if profile else None,
            "content": profile.research if profile else None,
            "error": profile.research_error if profile else None,
            "updated_at": _iso(profile.research_updated_at, tz) if profile else None,
        },
        "plan": action_plans.plan_dict(plan, tz, now),
    }
