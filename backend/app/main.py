import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routers import admin, public, webhooks
from app.services.booking_service import AlreadyBooked, BookingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="IAfluence Booking", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(public.router)
app.include_router(webhooks.router)
app.include_router(admin.router)


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
