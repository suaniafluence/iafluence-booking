"""Transactional emails sent through the Gmail API of the IAfluence account.

Recipients can use any provider (Gmail, Outlook, Proton, professional…) — R08.
"""

import base64
import logging
from collections.abc import Mapping
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config import get_config

log = logging.getLogger(__name__)

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    undefined=StrictUndefined,
    # .html templates (emails with a session summary) escape everything; .txt templates are plain text.
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
    trim_blocks=True,
)


def render(template: str, **ctx) -> str:
    return _env.get_template(template).render(**ctx)


class Mailer(Protocol):
    """`html` adds an HTML alternative to the text body; `images` are PNGs it shows with <img src="cid:KEY">."""

    def send(
        self, to: str, subject: str, body: str, *, html: str | None = None, images: Mapping[str, bytes] | None = None
    ) -> None: ...

    def draft(
        self, to: str, subject: str, body: str, *, html: str | None = None, images: Mapping[str, bytes] | None = None
    ) -> None:
        """Leave the email in the Gmail drafts of the sender, to be completed and sent by hand."""


def build_message(
    to: str, subject: str, body: str, *, html: str | None = None, images: Mapping[str, bytes] | None = None
) -> EmailMessage:
    """Plain text, or multipart/alternative (text + multipart/related HTML with its inline PNGs)."""
    cfg = get_config()
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.mail_from_name, cfg.mail_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
        html_part = msg.get_payload()[1]
        for cid, png in (images or {}).items():
            html_part.add_related(png, "image", "png", cid=f"<{cid}>", filename=f"{cid}.png", disposition="inline")
    return msg


class GmailMailer:
    def __init__(self, api_factory=None):
        if api_factory is None:
            from app.services.google_client import gmail_api

            api_factory = gmail_api
        self._api = api_factory

    @staticmethod
    def _raw(to: str, subject: str, body: str, **parts) -> str:
        return base64.urlsafe_b64encode(build_message(to, subject, body, **parts).as_bytes()).decode()

    def send(self, to: str, subject: str, body: str, **parts) -> None:
        raw = self._raw(to, subject, body, **parts)
        self._api().users().messages().send(userId="me", body={"raw": raw}).execute()

    def draft(self, to: str, subject: str, body: str, **parts) -> None:
        # Needs the gmail.compose scope (scripts.google_oauth_init).
        raw = self._raw(to, subject, body, **parts)
        self._api().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()


def send_safely(
    mailer: Mailer,
    to: str,
    subject: str,
    body: str,
    *,
    as_draft: bool = False,
    html: str | None = None,
    images: Mapping[str, bytes] | None = None,
) -> bool:
    """Emails never break the business flow: failures are logged for manual follow-up."""
    if not to:
        log.warning("email '%s' skipped: no recipient", subject)
        return False
    parts = {"html": html, "images": images} if html is not None else {}
    try:
        (mailer.draft if as_draft else mailer.send)(to, subject, body, **parts)
        return True
    except Exception:
        log.exception("email '%s' to %s failed", subject, to)
        return False
