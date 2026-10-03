"""Action plans: Codex drafts the consultant's plan for a customer, then the consultant refines it by chat.

    pending -> generating -> ready | failed     (each consultant message moves the plan back to pending)

- A purchase by a customer who had a discovery call creates the plan by itself (`on_purchase`). It waits for the
  call's summary while that summary is still being written, so the plan starts from what was said.
- Everything is a conversation: the first draft is a turn without message, « Régénérer » a turn asking for a full
  rewrite. Codex returns its answer and the whole plan, validated (app.services.plan_content) before replacing it.
- A turn takes minutes: the plan is claimed (`claimed_until`) instead of holding a row lock, like the session
  reports. The chat runs it right away in the background; the job loop catches anything left (crash, purchase).
- The dossier holds no transcript: only the summaries, the company profile and the consultant's notes.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import SessionLocal
from app.models import ActionPlan, ActionPlanMessage, Booking, Customer, CustomerProfile, Purchase, SessionReport
from app.services import learners, plan_content, report_content
from app.services.codex import CodexGateway, CodexNotConnected, CodexTurnFailed, CodexUnavailable
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
CLAIM_MARGIN = timedelta(minutes=5)
MAX_MESSAGE_CHARS = 4000
HISTORY_MESSAGES = 20
REWRITE_REQUEST = "Réécris entièrement le plan à partir du dossier à jour."
# The discovery summary is awaited this long after the purchase, then the plan is written without it.
SUMMARY_WAIT = timedelta(hours=8)


class PlanError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def busy(plan: ActionPlan | None) -> bool:
    return plan is not None and plan.status in ("pending", "generating")


def plan_dict(plan: ActionPlan | None, tz: ZoneInfo, now: datetime) -> dict | None:
    if plan is None:
        return None
    iso = lambda v: v.astimezone(tz).isoformat() if v else None  # noqa: E731
    return {
        "id": plan.id,
        "status": plan.status,
        "busy": busy(plan),
        "content": plan.content,
        "error": plan.error,
        "version": plan.version,
        "validated_at": iso(plan.validated_at),
        "updated_at": iso(plan.updated_at),
        "messages": [{"role": m.role, "content": m.content, "created_at": iso(m.created_at)} for m in plan.messages],
    }


def _locked_plan(db: Session, customer_id: int) -> ActionPlan | None:
    return db.scalar(select(ActionPlan).where(ActionPlan.customer_id == customer_id).with_for_update())


def request(db: Session, customer: Customer, consultant_id: int | None, now: datetime, message: str | None = None) -> ActionPlan:
    """« Générer le plan », « Régénérer » (REWRITE_REQUEST) or a chat message: queue a Codex turn."""
    if message is not None:
        message = message.strip()
        if not message:
            raise PlanError("Message vide.", 422)
        if len(message) > MAX_MESSAGE_CHARS:
            raise PlanError(f"Message trop long ({MAX_MESSAGE_CHARS} caractères au plus).", 422)
    plan = _locked_plan(db, customer.id)
    if busy(plan):
        db.rollback()
        raise PlanError("Le plan est en cours de rédaction : attendez la réponse.")
    if plan is None:
        if message is not None:
            db.rollback()
            raise PlanError("Générez d'abord le plan.", 404)
        plan = ActionPlan(customer_id=customer.id, consultant_id=consultant_id, status="pending", created_at=now)
        db.add(plan)
    else:
        plan.status, plan.error, plan.claimed_until = "pending", None, None
        if message is not None:
            plan.messages.append(ActionPlanMessage(role="consultant", content=message, created_at=now))
    plan.updated_at = now
    db.commit()
    return plan


def validate(db: Session, customer: Customer, validated: bool, now: datetime) -> ActionPlan:
    plan = _locked_plan(db, customer.id)
    if plan is None or plan.content is None:
        db.rollback()
        raise PlanError("Pas encore de plan à valider.", 404)
    plan.validated_at = now if validated else None
    db.commit()
    return plan


def on_purchase(db: Session, purchase: Purchase, now: datetime) -> bool:
    """Hours bought after a discovery call: the plan is written by itself (once per customer)."""
    had_call = db.scalar(
        select(Booking.id).where(
            Booking.customer_id == purchase.customer_id, Booking.kind == "discovery", Booking.status == "completed"
        )
    )
    if had_call is None:
        return False
    plan = _locked_plan(db, purchase.customer_id)
    if plan is not None:
        db.rollback()
        return False
    customer = db.get(Customer, purchase.customer_id)
    db.add(
        ActionPlan(
            customer_id=customer.id,
            consultant_id=customer.consultant_id,
            purchase_id=purchase.id,
            status="pending",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    log.info("action plan queued for customer %s after purchase %s", customer.id, purchase.id)
    return True


# --- the dossier given to Codex ------------------------------------------------------------------------------------


def _summary_pending(db: Session, customer_id: int, plan: ActionPlan, now: datetime) -> bool:
    """A discovery summary still being written, recently enough to be worth waiting for."""
    if now - plan.created_at > SUMMARY_WAIT:
        return False
    return (
        db.scalar(
            select(SessionReport.id)
            .join(Booking, Booking.id == SessionReport.booking_id)
            .where(
                Booking.customer_id == customer_id,
                Booking.kind == "discovery",
                SessionReport.status.in_(("waiting_transcript", "summarizing")),
            )
        )
        is not None
    )


def dossier(db: Session, customer: Customer, plan: ActionPlan, now: datetime) -> tuple[dict, str | None, int, int]:
    """(dossier, consultant message or None, sessions to plan, session length in minutes)."""
    settings = get_settings(db)
    tz = settings.timezone
    bookings = list(db.scalars(select(Booking).where(Booking.customer_id == customer.id).order_by(Booking.start_datetime)))
    act = learners.activity(customer, bookings, now)
    reports = {
        r.booking_id: r
        for r in db.scalars(select(SessionReport).where(SessionReport.booking_id.in_([b.id for b in bookings])))
    }
    profile = db.get(CustomerProfile, customer.id)

    def when(b: Booking) -> str:
        return b.start_datetime.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M")

    calls = [b for b in bookings if b.kind == "discovery" and b.status != "cancelled"]
    sessions = [b for b in bookings if b.kind in ("session", "meeting") and b.status == "completed"]
    sessions_to_plan = act.sessions_to_deliver
    data = {
        "consultant": settings.consultant_name,
        "client": {"nom": customer.name, "entreprise": customer.company_name, "notes_consultant": customer.notes},
        "entreprise": profile.company if profile else None,
        "recherche_web": profile.research if profile and profile.research_status == "ready" else None,
        "appel_decouverte": [
            {
                "date": when(b),
                "sujet_indique_par_le_prospect": b.message,
                "compte_rendu": reports[b.id].summary if b.id in reports else None,
            }
            for b in calls
        ],
        "accompagnement": {
            "prestations": [p.product_name for p in act.paid],
            "heures_achetees": act.hours_purchased,
            "seances_realisees": act.sessions_done,
            "seances_a_planifier": sessions_to_plan,
            "duree_seance_min": settings.booking_duration_min,
            "prochaine_seance": when(act.upcoming) if act.upcoming else None,
        },
        "seances_passees": [
            {"date": when(b), "type": b.kind, "titre": b.title, "compte_rendu": reports[b.id].summary if b.id in reports else None}
            for b in sessions
        ],
    }
    message = None
    if plan.content is not None:
        data["plan_actuel"] = plan.content
        history = plan.messages[-HISTORY_MESSAGES:]
        if history and history[-1].role == "consultant":
            message = history[-1].content
            history = history[:-1]
        data["conversation"] = [{"role": m.role, "message": m.content} for m in history]
    return data, message, sessions_to_plan, settings.booking_duration_min


# --- the Codex turn --------------------------------------------------------------------------------------------------


def _claim(now: datetime, plan_id: int | None = None) -> int | None:
    """Take one plan due for a turn: pending, or generating whose holder vanished."""
    until = now + timedelta(seconds=get_config().codex_turn_timeout_seconds) * MAX_ATTEMPTS + CLAIM_MARGIN
    with SessionLocal() as db:
        stmt = select(ActionPlan).where(
            or_(
                ActionPlan.status == "pending",
                (ActionPlan.status == "generating") & (ActionPlan.claimed_until < now),
            )
        )
        if plan_id is not None:
            stmt = stmt.where(ActionPlan.id == plan_id)
        for plan in db.scalars(stmt.order_by(ActionPlan.updated_at).with_for_update(skip_locked=True)):
            if plan.content is None and _summary_pending(db, plan.customer_id, plan, now):
                continue
            plan.status, plan.claimed_until = "generating", until
            db.commit()
            return plan.id
        db.rollback()
    return None


def _finish(plan_id: int, apply: Callable[[ActionPlan], None]) -> None:
    with SessionLocal() as db:
        plan = db.scalar(select(ActionPlan).where(ActionPlan.id == plan_id).with_for_update())
        if plan is not None and plan.status == "generating":
            apply(plan)
            plan.claimed_until = None
        db.commit()


def run(codex: CodexGateway, plan_id: int, now: datetime) -> None:
    with SessionLocal() as db:
        plan = db.get(ActionPlan, plan_id)
        data, message, sessions_to_plan, session_min = dossier(db, plan.customer, plan, now)

    def failed(problem: str):
        def apply(plan: ActionPlan) -> None:
            plan.status, plan.error = "failed", problem

        return apply

    instructions = report_content.agent_instructions(plan_content.AGENT_DIR)
    problem = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = plan_content.build_prompt(data, message)
        if problem:
            prompt += f"\nTa réponse précédente a été refusée : {problem}. Respecte exactement le format et le budget.\n"
        try:
            output = plan_content.parse(
                codex.run_turn(instructions=instructions, prompt=prompt, output_schema=plan_content.OUTPUT_SCHEMA),
                sessions_to_plan,
                session_min,
            )
            break
        except CodexNotConnected:
            return _finish(plan_id, failed("Codex n'est pas connecté : connectez-le dans l'administration."))
        except (report_content.InvalidOutput, CodexTurnFailed, CodexUnavailable) as e:
            problem = str(e)
            log.warning("action plan %s: attempt %d failed: %s", plan_id, attempt, type(e).__name__)
    else:
        return _finish(plan_id, failed(f"Plan impossible à rédiger : {problem}"))

    def ready(plan: ActionPlan) -> None:
        plan.content = output.plan.model_dump()
        plan.status, plan.error = "ready", None
        plan.version += 1
        plan.validated_at = None
        plan.messages.append(ActionPlanMessage(role="assistant", content=output.reponse, created_at=now))

    _finish(plan_id, ready)


def run_now(codex: CodexGateway, plan_id: int, clock: Callable[[], datetime]) -> None:
    """Background task of the chat: this plan's turn at once, if no other process took it."""
    now = clock()
    if _claim(now, plan_id) is not None:
        run(codex, plan_id, now)


def process(codex: CodexGateway, now: datetime) -> None:
    """One plan per cycle (a turn takes minutes)."""
    if (plan_id := _claim(now)) is not None:
        run(codex, plan_id, now)


async def run_forever(codex_factory: Callable[[], CodexGateway], interval_s: float, clock: Callable[[], datetime]) -> None:
    while True:
        try:
            await asyncio.to_thread(process, codex_factory(), clock())
        except Exception:
            log.exception("action plan job failed")
        await asyncio.sleep(interval_s)

