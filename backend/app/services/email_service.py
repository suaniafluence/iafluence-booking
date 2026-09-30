"""Transactional emails sent through the Gmail API of the IAfluence account.

Recipients can use any provider (Gmail, Outlook, Proton, professional…) — R08.
"""

import base64
import logging
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.config import get_config

log = logging.getLogger(__name__)

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
)


def render(template: str, **ctx) -> str:
    return _env.get_template(template).render(**ctx)


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...

    def draft(self, to: str, subject: str, body: str) -> None:
        """Leave the email in the Gmail drafts of the sender, to be completed and sent by hand."""


class GmailMailer:
    def __init__(self, api_factory=None):
        if api_factory is None:
            from app.services.google_client import gmail_api

            api_factory = gmail_api
        self._api = api_factory

    @staticmethod
    def _raw(to: str, subject: str, body: str) -> str:
        cfg = get_config()
        msg = EmailMessage()
        msg["From"] = formataddr((cfg.mail_from_name, cfg.mail_from))
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def send(self, to: str, subject: str, body: str) -> None:
        self._api().users().messages().send(userId="me", body={"raw": self._raw(to, subject, body)}).execute()

    def draft(self, to: str, subject: str, body: str) -> None:
        # Needs the gmail.compose scope (scripts.google_oauth_init).
        raw = self._raw(to, subject, body)
        self._api().users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()


def send_safely(mailer: Mailer, to: str, subject: str, body: str, *, as_draft: bool = False) -> bool:
    """Emails never break the business flow: failures are logged for manual follow-up."""
    if not to:
        log.warning("email '%s' skipped: no recipient", subject)
        return False
    try:
        (mailer.draft if as_draft else mailer.send)(to, subject, body)
        return True
    except Exception:
        log.exception("email '%s' to %s failed", subject, to)
        return False
