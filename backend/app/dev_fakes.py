"""In-memory stand-ins for Google, Stripe, Gmail, Fireflies and Codex, for local demos only (FAKE_INTEGRATIONS=true).

- Any checkout session id of the form `cs_demo_<hours>h_<anything>` is a paid purchase,
  e.g. /reservation?session_id=cs_demo_5h_jean
- Calendars have a few fixed busy periods; created events are kept in memory.
- Emails are printed to the log instead of being sent (and saved as .eml files if DEMO_OUTBOX_DIR is set).
- Fireflies has a recording of every booked session; « Connecter Codex » succeeds on its own after a few seconds,
  and the demo agent writes a summary from the session context.
"""

import json
import logging
import re
import secrets
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import get_config
from app.services.availability import Interval
from app.services.calendar_service import BusyEvent, CreatedEvent
from app.services.codex import CodexAccount, CodexNotConnected, DeviceCode
from app.services.email_service import build_message
from app.services.fireflies import Sentence, TranscriptMeta

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

    def busy_events(self, calendar_id, time_min: datetime, time_max: datetime, tz):
        """The same periods, plus a lunch « Déjeuner ? » on Fridays that is not fixed yet."""
        events = [BusyEvent(i.start, i.end) for i in self.free_busy([calendar_id], time_min, time_max)]
        day = time_min.astimezone(PARIS).date()
        while day <= time_max.astimezone(PARIS).date():
            if day.weekday() == 4:
                events.append(BusyEvent(datetime.combine(day, time(12), PARIS), datetime.combine(day, time(14), PARIS), True))
            day += timedelta(days=1)
        return events

    def create_event(self, calendar_id, **kw):
        with self._lock:
            self._events.append(Interval(kw["start"], kw["end"]))
        log.info("[demo] event created: %s %s -> %s", kw["summary"], kw["start"], kw["end"])
        code = uuid.uuid4().hex
        return CreatedEvent(event_id=f"demo_{code[:8]}", meet_url=f"https://meet.google.com/{code[:3]}-{code[3:7]}-{code[7:10]}")

    def delete_event(self, calendar_id, event_id):
        log.info("[demo] event deleted: %s", event_id)


class DemoMailer:
    def __init__(self):
        self._count = 0
        self._lock = threading.Lock()

    def _save(self, kind, to, subject, body, parts):
        outbox = get_config().demo_outbox_dir
        if not outbox:
            return
        with self._lock:
            self._count += 1
            name = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{self._count:04d}-{kind}.eml"
        Path(outbox).mkdir(parents=True, exist_ok=True)
        (Path(outbox) / name).write_bytes(build_message(to, subject, body, **parts).as_bytes())

    def send(self, to, subject, body, **parts):
        log.info("[demo] email to %s — %s\n%s", to, subject, body)
        self._save("sent", to, subject, body, parts)

    def draft(self, to, subject, body, **parts):
        log.info("[demo] draft to %s — %s\n%s", to, subject, body)
        self._save("draft", to, subject, body, parts)


class DemoFireflies:
    """Every session booked in the demo was « recorded »: its transcript is a short canned conversation."""

    def list_transcripts(self, time_min, time_max):
        from app.db import SessionLocal
        from app.models import Booking

        with SessionLocal() as db:
            bookings = db.scalars(
                select(Booking).where(Booking.start_datetime >= time_min, Booking.start_datetime <= time_max)
            ).all()
            return [
                TranscriptMeta(
                    id=f"demo_{b.id}",
                    start=b.start_datetime,
                    emails=frozenset({b.customer.email.lower(), "contact@iafluence.fr"}),
                    meeting_link=b.meet_url,
                )
                for b in bookings
            ]

    def sentences(self, transcript_id):
        return [
            Sentence("Consultant", "Bonjour ! Aujourd'hui, on fait le point sur vos usages de l'IA générative."),
            Sentence("Client", "Je voudrais automatiser les réponses aux demandes de devis."),
            Sentence("Consultant", "Commençons par un assistant qui prépare un brouillon à partir de vos modèles."),
            Sentence("Client", "D'accord, je rassemble dix exemples de devis pour la prochaine fois."),
        ]


DEMO_LOGIN_DELAY_S = 4


class DemoCodex:
    """Device login approved « on the OpenAI page » after DEMO_LOGIN_DELAY_S; the agent answers without a model."""

    def __init__(self):
        self.connected = False
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def account(self):
        return CodexAccount(email="demo@iafluence.fr", plan="plus") if self.connected else None

    def start_login(self, on_done):
        login_id = uuid.uuid4().hex

        def approve():
            with self._lock:
                self._timers.pop(login_id, None)
                self.connected = True
            on_done(login_id, "COMPLETED", None)

        timer = threading.Timer(DEMO_LOGIN_DELAY_S, approve)
        timer.daemon = True
        with self._lock:
            self._timers[login_id] = timer
        timer.start()
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        code = "".join(secrets.choice(alphabet) for _ in range(4)) + "-" + f"{secrets.randbelow(10_000):04d}"
        return DeviceCode(login_id, "https://auth.openai.com/codex/device", code)

    def cancel_login(self, login_id):
        with self._lock:
            timer = self._timers.pop(login_id, None)
        if timer:
            timer.cancel()

    def logout(self):
        self.connected = False

    def run_turn(self, *, instructions, prompt, output_schema):
        if not self.connected:
            raise CodexNotConnected("Codex n'est pas connecté")
        ctx = json.loads(prompt.split("Contexte de la séance (JSON) :\n", 1)[1].split("\n\nTranscription", 1)[0])
        number, client = ctx["seance_numero"], ctx["client"]
        last = ctx["derniere_seance"]
        synthese = {
            "objectifs": ["Identifier les usages de l'IA générative les plus utiles à votre activité"],
            "points_abordes": [
                "Automatisation des réponses aux demandes de devis",
                "Assistant qui prépare un brouillon à partir de vos modèles",
            ],
            "decisions": ["Commencer par un assistant de rédaction de devis"],
            "actions_client": ["Rassembler dix exemples de devis représentatifs"],
            "prochaines_etapes": (
                ["Poursuivre en autonomie avec la méthode vue ensemble"]
                if last
                else ["Construire et tester l'assistant lors de la prochaine séance"]
            ),
        }
        return json.dumps({"synthese": synthese, "image": demo_infographic(number, client, synthese)}, ensure_ascii=False)


def demo_infographic(number: int, client: str, synthese: dict) -> str:
    from textwrap import wrap
    from xml.sax.saxutils import escape

    blocks = [
        ("Points clés", synthese["points_abordes"]),
        ("Décisions", synthese["decisions"]),
        ("Vos actions", synthese["actions_client"]),
        ("Prochaines étapes", synthese["prochaines_etapes"]),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800">',
        '<rect width="1200" height="800" fill="#eef2ff"/>',
        '<rect x="0" y="0" width="1200" height="120" fill="#1e1b4b"/>',
        f'<text x="60" y="78" font-family="DejaVu Sans, sans-serif" font-size="40" fill="#ffffff">'
        f"Séance n° {number} — {escape(client)}</text>",
    ]
    for i, (title, items) in enumerate(blocks):
        x, y = 60 + (i % 2) * 560, 170 + (i // 2) * 300
        parts.append(f'<rect x="{x}" y="{y}" width="520" height="260" rx="24" fill="#ffffff" stroke="#c7d2fe"/>')
        parts.append(
            f'<text x="{x + 30}" y="{y + 55}" font-family="DejaVu Sans, sans-serif" font-size="30" '
            f'font-weight="bold" fill="#4338ca">{escape(title)}</text>'
        )
        lines = [line for item in items[:2] for line in wrap(f"• {item}", 36, max_lines=2, placeholder=" …")]
        for j, line in enumerate(lines[:4]):
            parts.append(
                f'<text x="{x + 30}" y="{y + 105 + j * 38}" font-family="DejaVu Sans, sans-serif" font-size="22" '
                f'fill="#1e1b4b">{escape(line)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


class DemoStripe:
    # Optional language suffix, like a payment link opened with ?locale=en: cs_demo_5h_john_en
    PATTERN = re.compile(r"^cs_demo_(\d+)h_([a-z0-9]+)(?:_(fr|en|es))?$")

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
            "locale": m.group(3),
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
