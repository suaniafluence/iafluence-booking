import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_config
from app.deps import get_codex, get_fireflies, get_mailer, get_now
from app.routers import admin, auth, consultant, mcp, public, webhooks
from app.services import action_plans, follow_up, session_reports
from app.services.booking_service import AlreadyBooked, BookingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def report_gateways() -> session_reports.Gateways:
    return session_reports.Gateways(mailer=get_mailer(), fireflies=get_fireflies(), codex=get_codex())


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = get_config()
    interval = cfg.follow_up_poll_seconds
    tasks = []
    if interval > 0:
        tasks.append(asyncio.create_task(follow_up.run_forever(get_mailer, interval)))
        if cfg.codex_enabled:
            # Its own loop: a Codex turn lasts minutes and must not delay the closing of sessions.
            tasks.append(asyncio.create_task(session_reports.run_forever(report_gateways, interval, get_now)))
            # Action plans queued by a purchase, or left behind by a restart during a chat turn.
            tasks.append(asyncio.create_task(action_plans.run_forever(get_codex, interval, get_now)))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="IAfluence Booking", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(public.router)
app.include_router(webhooks.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(consultant.router)
app.include_router(mcp.router)


@app.exception_handler(BookingError)
def booking_error_handler(_: Request, exc: BookingError):
    content = {"detail": exc.message, "code": exc.code}
    if isinstance(exc, AlreadyBooked):
        content["booking"] = {
            "start": exc.booking.start_datetime.isoformat(),
            "end": exc.booking.end_datetime.isoformat(),
            "meet_url": exc.booking.meet_url,
        }
    return JSONResponse(status_code=exc.status_code, content=content)


@app.get("/api/health")
def health():
    return {"status": "ok"}
