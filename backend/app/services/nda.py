"""Confidentiality agreement (NDA), exchanged by email before the first meeting.

The admin uploads the agreement already signed by the consultant (one PDF per language, French as the fallback).
A customer asks for it with a box on the discovery form or on the confirmation of their first paid session, or
the admin sends it from the admin page. The customer signs it and returns it by replying to the email; the admin
then ticks « Signé reçu ». The mailbox itself is never read.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import i18n
from app.db import SessionLocal
from app.models import Customer, NdaDocument
from app.services.email_service import Mailer, render, send_safely
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 5 * 1024 * 1024
DEFAULT_FILENAME = "NDA-IAfluence.pdf"


class NdaError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code:
            self.status_code = status_code


def available(db: Session) -> bool:
    """The box is offered once the French agreement (the fallback of every language) is uploaded."""
    return db.get(NdaDocument, i18n.DEFAULT_LOCALE) is not None


def document(db: Session, locale: str) -> NdaDocument | None:
    return db.get(NdaDocument, locale) or db.get(NdaDocument, i18n.DEFAULT_LOCALE)


def clean_filename(raw: str | None) -> str:
    """Keep a readable name for the attachment, without any path or header-breaking character."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '"<>|:*?').strip()[:200]
    if not name:
        return DEFAULT_FILENAME
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def upload(db: Session, locale: str, filename: str | None, pdf: bytes, now: datetime) -> NdaDocument:
    if i18n.normalize_locale(locale) != locale:
        raise NdaError("Langue inconnue.", 404)
    if not pdf.startswith(b"%PDF-"):
        raise NdaError("Ce fichier n'est pas un PDF.", 422)
    if len(pdf) > MAX_PDF_BYTES:
        raise NdaError("PDF trop lourd : 5 Mo au plus.", 413)
    doc = db.get(NdaDocument, locale) or NdaDocument(locale=locale)
    doc.filename, doc.pdf = clean_filename(filename), pdf
    doc.uploaded_at = now
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def remove(db: Session, locale: str) -> None:
    doc = db.get(NdaDocument, locale)
    if doc is None:
        raise NdaError("Aucun PDF pour cette langue.", 404)
    db.delete(doc)
    db.commit()


@dataclass(frozen=True)
class NdaEmail:
    to: str
    subject: str
    body: str
    filename: str
    pdf: bytes


def prepare(db: Session, customer: Customer, locale: str) -> NdaEmail | None:
    doc = document(db, locale)
    if doc is None:
        return None
    locale = i18n.normalize_locale(locale) or i18n.DEFAULT_LOCALE
    settings = get_settings(db)
    body = render(f"{locale}/nda.txt", name=customer.name, consultant_name=settings.consultant_name)
    return NdaEmail(customer.email, i18n.text(locale, "subject_nda"), body, doc.filename, doc.pdf)


def deliver(mailer: Mailer, email: NdaEmail) -> bool:
    return send_safely(mailer, email.to, email.subject, email.body, attachments=[(email.filename, email.pdf)])


def send_requested(mailer: Mailer, customer_id: int, locale: str) -> None:
    """Background task after a booking whose box was ticked. Sent once per person: anyone can type an email on
    the public form, so an address that already received it is not sent it again (the admin can resend)."""
    with SessionLocal() as db:
        customer = db.get(Customer, customer_id)
        if customer.nda_sent_at is not None:
            log.info("NDA already sent to customer %s: not sent again", customer_id)
            return
        email = prepare(db, customer, locale)
        if email is None:
            log.warning("NDA asked by customer %s but no PDF is uploaded", customer_id)
            return
        if deliver(mailer, email):
            customer.nda_sent_at = datetime.now(UTC)
            db.commit()


def send_now(db: Session, mailer: Mailer, *, name: str, email: str, locale: str, now: datetime) -> Customer:
    """« Envoyer le NDA » from the admin, to a client or anyone else (created as a contact if unknown); Gmail is
    called before answering so the admin sees a failure at once. A known customer keeps their name."""
    db.execute(pg_insert(Customer).values(name=name, email=email).on_conflict_do_nothing(index_elements=[Customer.email]))
    customer = db.scalar(select(Customer).where(Customer.email == email))
    message = prepare(db, customer, locale)
    if message is None:
        db.rollback()
        raise NdaError("Téléversez d'abord le NDA signé (PDF).", 409)
    if not deliver(mailer, message):
        db.rollback()
        raise NdaError("Gmail a refusé l'email du NDA (voir les logs de l'API).", 502)
    customer.nda_sent_at = now
    db.commit()
    return customer


def set_signed(db: Session, customer_id: int, signed: bool, now: datetime) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NdaError("Client introuvable.", 404)
    if signed and customer.nda_sent_at is None:
        raise NdaError("Le NDA n'a pas encore été envoyé à ce client.", 409)
    customer.nda_signed_at = (customer.nda_signed_at or now) if signed else None
    db.commit()
    return customer


def overview(db: Session, tz: ZoneInfo) -> dict:
    docs = db.scalars(select(NdaDocument).order_by(NdaDocument.locale)).all()
    customers = db.scalars(
        select(Customer).where(Customer.nda_sent_at.is_not(None)).order_by(Customer.nda_sent_at.desc()).limit(200)
    ).all()

    def iso(dt: datetime | None) -> str | None:
        return dt.astimezone(tz).isoformat() if dt else None

    return {
        "documents": [
            {"locale": d.locale, "filename": d.filename, "size": len(d.pdf), "uploaded_at": iso(d.uploaded_at)}
            for d in docs
        ],
        "customers": [
            {
                "customer_id": c.id,
                "name": c.name,
                "email": c.email,
                "sent_at": iso(c.nda_sent_at),
                "signed_at": iso(c.nda_signed_at),
            }
            for c in customers
        ],
    }
