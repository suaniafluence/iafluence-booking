"""Transactional emails sent through the Gmail API of the IAfluence account.

Recipients can use any provider (Gmail, Outlook, Proton, professional…) — R08.
"""

import base64
import logging
import re
from collections.abc import Mapping, Sequence
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
    cfg = get_config()
    # The HTML layout links the logo of the website rather than attaching it to every email.
    links = {"site_url": cfg.shop_url, "logo_url": f"{cfg.public_base_url.rstrip('/')}/logo.jpg"}
    # Language of the layout (and of its personal data notice): the folder of the template, French otherwise.
    folder = template.split("/", 1)[0]
    ctx.setdefault("lang", folder if folder in ("fr", "en", "es") else "fr")
    return _env.get_template(template).render(**links, **ctx)


# --- HTML version of the plain-text emails -------------------------------------------------------------------------
# Every email goes out in the IAfluence layout (templates/_layout.html). Text emails are written as plain text; their
# HTML version is derived from it: "Label :" followed by its value becomes a card, a link alone in its paragraph a
# button, the closing "Name / IAfluence" the signature.

_URL = re.compile(r"https?://[^\s<>]+")
_LABEL = re.compile(r"^(?P<label>[^:]{1,40}?)\s*:$")
# Button text by kind of link, in the language of the greeting (admin emails have none: French).
_BUTTON = {
    "booking": {"fr": "Choisir mon créneau", "en": "Pick my time", "es": "Elegir mi horario"},
    "meet": {"fr": "Rejoindre la visio", "en": "Join the video call", "es": "Unirse a la videollamada"},
    "link": {"fr": "Ouvrir le lien", "en": "Open the link", "es": "Abrir el enlace"},
}
_GREETING = {"hello": "en", "hi": "en", "dear": "en", "hola": "es", "estimado": "es", "estimada": "es"}


def _lang(body: str) -> str:
    first = body.lstrip().split(maxsplit=1)
    word = first[0].strip(",:").lower() if first else ""
    return _GREETING.get(word, "fr")


def _button_label(url: str, lang: str) -> str:
    kind = "booking" if "/reservation/" in url else "meet" if "meet.google.com" in url else "link"
    return _BUTTON[kind][lang]


def _segments(line: str) -> list[dict]:
    out, pos = [], 0
    for m in _URL.finditer(line):
        url = m.group().rstrip(".,;)")
        if m.start() > pos:
            out.append({"text": line[pos : m.start()], "href": None})
        out.append({"text": url, "href": url})
        pos = m.start() + len(url)
    if pos < len(line):
        out.append({"text": line[pos:], "href": None})
    return out


def _blocks(body: str, lang: str) -> list[dict]:
    paragraphs = [p.splitlines() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    blocks: list[dict] = []
    for i, lines in enumerate(paragraphs):
        lines = [line.rstrip() for line in lines]
        label = _LABEL.match(lines[0])
        if label and len(lines) > 1:
            item = {"label": label["label"], "lines": [_segments(line) for line in lines[1:]]}
            if blocks and blocks[-1]["type"] == "fields":
                blocks[-1]["fields"].append(item)
            else:
                blocks.append({"type": "fields", "fields": [item]})
        elif len(lines) == 1 and _URL.fullmatch(lines[0].strip()):
            blocks.append({"type": "button", "href": lines[0].strip(), "label": _button_label(lines[0].strip(), lang)})
        elif i == len(paragraphs) - 1 and lines[-1].strip() == "IAfluence" and len(lines) <= 3:
            blocks.append({"type": "signature", "lines": [line.strip() for line in lines]})
        else:
            blocks.append({"type": "paragraph", "lines": [_segments(line) for line in lines]})
    return blocks


def html_from_text(body: str, subject: str = "IAfluence") -> str:
    lang = _lang(body)
    return render("_text.html", blocks=_blocks(body, lang), lang=lang, title=subject)


# (filename, PDF bytes)
Attachment = tuple[str, bytes]


class Mailer(Protocol):
    """`html` adds an HTML alternative to the text body; `images` are PNGs it shows with <img src="cid:KEY">;
    `attachments` are PDF files."""

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        html: str | None = None,
        images: Mapping[str, bytes] | None = None,
        attachments: Sequence[Attachment] | None = None,
    ) -> None: ...

    def draft(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        html: str | None = None,
        images: Mapping[str, bytes] | None = None,
        attachments: Sequence[Attachment] | None = None,
    ) -> None:
        """Leave the email in the Gmail drafts of the sender, to be completed and sent by hand."""


def build_message(
    to: str,
    subject: str,
    body: str,
    *,
    html: str | None = None,
    images: Mapping[str, bytes] | None = None,
    attachments: Sequence[Attachment] | None = None,
) -> EmailMessage:
    """multipart/alternative: the text, then its HTML (multipart/related with its inline PNGs), derived from the text
    in the IAfluence layout when not given; then the attached PDFs (multipart/mixed)."""
    cfg = get_config()
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.mail_from_name, cfg.mail_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_alternative(html if html is not None else html_from_text(body, subject), subtype="html")
    html_part = msg.get_payload()[1]
    for cid, png in (images or {}).items():
        html_part.add_related(png, "image", "png", cid=f"<{cid}>", filename=f"{cid}.png", disposition="inline")
    for filename, data in attachments or ():
        msg.add_attachment(data, "application", "pdf", filename=filename)
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
    attachments: Sequence[Attachment] | None = None,
) -> bool:
    """Emails never break the business flow: failures are logged for manual follow-up."""
    if not to:
        log.warning("email '%s' skipped: no recipient", subject)
        return False
    parts = {"html": html, "images": images} if html is not None else {}
    if attachments:
        parts["attachments"] = attachments
    try:
        (mailer.draft if as_draft else mailer.send)(to, subject, body, **parts)
        return True
    except Exception:
        log.exception("email '%s' to %s failed", subject, to)
        return False
