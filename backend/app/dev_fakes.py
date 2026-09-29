"""In-memory stand-ins for Google and Stripe, for local demos only (FAKE_INTEGRATIONS=true).

- Any checkout session id of the form `cs_demo_<hours>h_<anything>` is a paid purchase,
  e.g. /reservation?session_id=cs_demo_5h_jean
- Calendars have a few fixed busy periods; created events are kept in memory.
- Emails are printed to the log instead of being sent.
"""

import logging
import re
import threading
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.availability import Interval
from app.services.calendar_service import CreatedEvent

log = logging.getLogger("dev_fakes")
PARIS = ZoneInfo("Europe/Paris")


class DemoCalendar:
    def __init__(self):
        self._events: list[Interval] = []
        self._lock = threading.Lock()

    def free_busy(self, calendar_ids, time_min: datetime, time_max: datetime):
        busy = []
        day = time_min.astimezone(PARIS).date()
        while day <= time_max.astimezone(PARIS).date():
            # A recurring 10:00-11:00 meeting on Tue/Thu and a 14:00-16:00 block on Wednesdays.
            if day.weekday() in (1, 3):
                busy.append(Interval(datetime.combine(day, time(10), PARIS), datetime.combine(day, time(11), PARIS)))
            if day.weekday() == 2:
                busy.append(Interval(datetime.combine(day, time(14), PARIS), datetime.combine(day, time(16), PARIS)))
            day += timedelta(days=1)
        with self._lock:
            return busy + list(self._events)

    def create_event(self, calendar_id, **kw):
        with self._lock:
            self._events.append(Interval(kw["start"], kw["end"]))
        log.info("[demo] event created: %s %s -> %s", kw["summary"], kw["start"], kw["end"])
        code = uuid.uuid4().hex
        return CreatedEvent(event_id=f"demo_{code[:8]}", meet_url=f"https://meet.google.com/{code[:3]}-{code[3:7]}-{code[7:10]}")

    def delete_event(self, calendar_id, event_id):
        log.info("[demo] event deleted: %s", event_id)


class DemoMailer:
    def send(self, to, subject, body):
        log.info("[demo] email to %s — %s\n%s", to, subject, body)


class DemoStripe:
    PATTERN = re.compile(r"^cs_demo_(\d+)h_([a-z0-9]+)$")

    def retrieve_checkout_session(self, session_id):
        from app.services.stripe_service import PaymentInvalid

        m = self.PATTERN.match(session_id)
        if not m:
            raise PaymentInvalid("unknown checkout session")
        hours, who = int(m.group(1)), m.group(2)
        return {
            "id": session_id,
            "payment_status": "paid",
            "payment_intent": f"pi_demo_{who}",
            "amount_total": 150_00 * hours,
            "currency": "eur",
            "customer_details": {"email": f"{who}@example.com", "name": who.capitalize() + " Démo"},
            "line_items": {
                "data": [
                    {
                        "quantity": 1,
                        "price": {
                            "product": {
                                "id": f"prod_demo_{hours}h",
                                "name": f"Conseil IA - {hours}h",
                                "metadata": {"hours": str(hours)},
                            }
                        },
                    }
                ]
            },
        }

    def construct_event(self, payload, signature):
        raise ValueError("webhooks are disabled in demo mode")
