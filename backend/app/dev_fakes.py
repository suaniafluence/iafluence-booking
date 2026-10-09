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
from app.services.fireflies import FirefliesAccount, Sentence, TranscriptMeta

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
    """Every session booked in the demo was « recorded »: its transcript is a short canned conversation.
    One more meeting, booked outside the app, was recorded at 10:30 (« Autres réunions » in the admin)."""

    def list_transcripts(self, time_min, time_max):
        from app.db import SessionLocal
        from app.models import Booking

        with SessionLocal() as db:
            bookings = db.scalars(
                select(Booking).where(
                    Booking.kind != "meeting", Booking.start_datetime >= time_min, Booking.start_datetime <= time_max
                )
            ).all()
            metas = [
                TranscriptMeta(
                    id=f"demo_{b.id}",
                    start=b.start_datetime,
                    emails=frozenset({b.customer.email.lower(), "contact@iafluence.fr"}),
                    meeting_link=b.meet_url,
                    title=f"{'Appel découverte' if b.kind == 'discovery' else 'Conseil IA'} - {b.customer.name}",
                    duration_min=(b.end_datetime - b.start_datetime).total_seconds() / 60,
                )
                for b in bookings
            ]
        now = datetime.now(PARIS)
        external = now.replace(hour=10, minute=30, second=0, microsecond=0)
        if external > now:
            external -= timedelta(days=1)
        if time_min <= external <= time_max:
            metas.append(
                TranscriptMeta(
                    id="demo_external",
                    start=external,
                    emails=frozenset({"claire@exemple.fr", "contact@iafluence.fr"}),
                    title="Point projet - Exemple SAS",
                    duration_min=45,
                )
            )
        return metas

    def account(self, api_key):
        return FirefliesAccount(email="demo@iafluence.fr", name="Démo IAfluence")

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

    def run_turn(self, *, instructions, prompt, output_schema, web_search=False):
        if not self.connected:
            raise CodexNotConnected("Codex n'est pas connecté")
        properties = output_schema.get("properties", {})
        if "plan" in properties:
            return demo_plan(prompt)
        if "activite_reelle" in properties:
            return demo_research(prompt)
        if "interlocuteurs" in properties:
            return demo_speakers(prompt)
        ctx = json.loads(prompt.split("Contexte de la séance (JSON) :\n", 1)[1].split("\n\nTranscription", 1)[0])
        number, client = ctx.get("seance_numero"), ctx["client"]
        last = ctx.get("derniere_seance", False)
        heading = {"appel_decouverte": "Appel découverte", "reunion": "Réunion"}.get(ctx.get("type_rdv"))
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
        image = demo_infographic(number, client, synthese, heading)
        return json.dumps({"synthese": synthese, "image": image}, ensure_ascii=False)


def demo_speakers(prompt: str) -> str:
    """The consultant and the client take turns, one segment each (or the speakers announced)."""
    ctx = json.loads(prompt.split("Contexte du rendez-vous (JSON) :\n", 1)[1].split("\n\nTranscription", 1)[0])
    count = int(prompt.split("Transcription collée, ", 1)[1].split(" segments", 1)[0])
    announced = ctx.get("interlocuteurs_annonces", {})
    names = announced.get("noms") or [ctx["consultant"], ctx["client"]]
    names = names[: announced.get("nombre") or len(names)]
    speakers = [{"nom": n, "role": "Consultant IAfluence" if i == 0 else "Participant"} for i, n in enumerate(names)]
    turns = [{"debut": i, "fin": i, "interlocuteur": (i - 1) % len(names) + 1} for i in range(1, count + 1)]
    return json.dumps({"interlocuteurs": speakers, "tours": turns}, ensure_ascii=False)


def _dossier(prompt: str) -> dict:
    return json.loads(prompt.split("<<<DOSSIER\n", 1)[1].split("\nDOSSIER>>>", 1)[0])


DEMO_TITLES = ["Cadrage et premier cas d'usage", "Prototype sur données réelles", "Déploiement à l'équipe"]


def demo_plan(prompt: str) -> str:
    """A plan that fits the sessions left, as the real agent must."""
    dossier = _dossier(prompt)
    time_ = dossier.get("accompagnement") or {}
    count = time_.get("seances_a_planifier") or 3
    minutes = time_.get("duree_seance_min") or 60
    chat = "message_consultant :" in prompt

    def session(n: int) -> dict:
        last = n == count
        return {
            "numero": n,
            "titre": "Autonomie et feuille de route" if last else DEMO_TITLES[(n - 1) % 3],
            "objectif": "Le client sait continuer seul" if last else "Un livrable testé sur un cas réel",
            "duree_min": minutes,
            "deroule": [
                {"minutes": 5, "activite": "Point sur les actions depuis la dernière séance"},
                {"minutes": minutes - 15, "activite": "Atelier sur le cas d'usage prioritaire, avec les documents du client"},
                {"minutes": 10, "activite": "Décisions, actions et préparation de la séance suivante"},
            ],
            "livrable": "Check-list et prompts maison" if last else "Prototype documenté",
            "preparation_client": ["Rassembler dix exemples réels du document à automatiser"],
        }

    plan = {
        "resume": f"Accompagnement de {dossier['client']['nom']} centré sur un premier cas d'usage rentable (démo).",
        "objectif": "Diviser par trois le temps de préparation des devis d'ici la fin du forfait",
        "diagnostic": ["Devis rédigés à la main, environ 1 h chacun (appel)", "Petite structure sans outil d'IA (appel)"],
        "priorites": [
            {
                "titre": "Assistant de rédaction de devis",
                "pourquoi": "Tâche répétitive citée en premier",
                "gain_attendu": "4 h par semaine",
                "effort": "faible",
            }
        ],
        "seances": [session(n) for n in range(1, count + 1)],
        "entre_les_seances": ["Tester l'assistant sur trois devis réels et noter les corrections"],
        "indicateurs": ["Temps moyen de préparation d'un devis"],
        "risques": [{"risque": "Données clients dans un outil grand public", "parade": "Compte professionnel, historique désactivé"}],
        "outils": [{"nom": "ChatGPT Team", "usage": "Rédaction assistée", "cout": "environ 30 € par mois et par utilisateur"}],
        "hypotheses_a_verifier": ["Les modèles de devis sont homogènes"],
        "questions_ouvertes": ["Qui valide les devis avant envoi ?"],
    }
    answer = (
        "C'est noté : j'ai ajusté le plan en conséquence (démo)."
        if chat
        else "Plan initial rédigé (démo) : vérifiez d'abord le volume réel de devis."
    )
    return json.dumps({"reponse": answer, "plan": plan}, ensure_ascii=False)


def demo_research(prompt: str) -> str:
    name = _dossier(prompt).get("entreprise") or "l'entreprise"
    return json.dumps(
        {
            "synthese": f"Note de démonstration : aucune recherche web n'a été faite pour {name}.",
            "activite_reelle": ["Activité à confirmer avec le client"],
            "personne": {"role": "", "linkedin_url": ""},
            "entreprise": {"site_web": "", "linkedin_url": ""},
            "signaux_positifs": [],
            "points_attention": [],
            "angles_ia": ["Réponses assistées aux demandes entrantes"],
            "questions_a_poser": ["Combien de demandes recevez-vous par semaine ?"],
            "sources": [],
            "confiance": "faible",
        },
        ensure_ascii=False,
    )


def demo_infographic(number: int | None, client: str, synthese: dict, heading: str | None = None) -> str:
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
        f"{escape(heading or f'Séance n° {number}')} — {escape(client)}</text>",
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


class DemoSso:
    """« Google » signs in at once, as the address typed on the sign-in page (or the first staff account)."""

    def __init__(self):
        self._flows: dict[str, tuple[str, str | None]] = {}

    def authorization_url(self, *, redirect_uri, state, nonce, code_challenge, login_hint=None):
        from urllib.parse import urlencode

        code = secrets.token_urlsafe(16)
        self._flows[code] = (nonce, login_hint)
        return f"{redirect_uri}?{urlencode({'code': code, 'state': state})}"

    def exchange(self, *, code, redirect_uri, code_verifier):
        from app.db import SessionLocal
        from app.models import StaffUser
        from app.services.google_sso import GoogleIdentity, SsoError

        if code not in self._flows:
            raise SsoError("code inconnu")
        nonce, email = self._flows.pop(code)
        if not email:
            with SessionLocal() as db:
                email = db.scalar(select(StaffUser.email).where(StaffUser.active).order_by(StaffUser.id)) or ""
        return GoogleIdentity(sub=f"demo-{email}", email=email.lower(), email_verified=True, name="", nonce=nonce)


class DemoCompanyRegister:
    """One fictitious company, whatever is searched."""

    def search(self, query):
        return [
            {
                "siren": "123456789",
                "nom_complet": f"{query.upper()[:40]} (DÉMO)",
                "etat_administratif": "A",
                "date_creation": "2016-03-01",
                "categorie_entreprise": "PME",
                "nature_juridique": "5710",
                "activite_principale": "70.22Z",
                "tranche_effectif_salarie": "11",
                "annee_tranche_effectif_salarie": "2023",
                "nombre_etablissements_ouverts": 1,
                "siege": {"adresse": "1 RUE DE LA DÉMO 75001 PARIS"},
                "dirigeants": [
                    {"type_dirigeant": "personne physique", "nom": "DÉMO", "prenoms": "Camille", "qualite": "Président"}
                ],
                "finances": {"2023": {"ca": 820000, "resultat_net": 41000}, "2022": {"ca": 700000, "resultat_net": 30000}},
                "complements": {"est_organisme_formation": True},
            }
        ]
