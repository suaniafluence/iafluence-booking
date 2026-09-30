"""French formatting, email rendering and Gmail sending — pure, no database."""

import base64
import email
from datetime import UTC, datetime
from email import policy

import pytest
from jinja2 import UndefinedError

from app.config import Config
from app.services import email_service
from app.services import formatting as fmt
from app.services.email_service import GmailMailer, render, send_safely

TZ = "Europe/Paris"


# --- formatting ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "dt, expected",
    [
        (datetime(2026, 10, 8, 12, tzinfo=UTC), "Jeudi 8 octobre 2026"),
        (datetime(2026, 1, 5, 9, tzinfo=UTC), "Lundi 5 janvier 2026"),
        (datetime(2026, 8, 16, 9, tzinfo=UTC), "Dimanche 16 août 2026"),
        (datetime(2026, 12, 31, 23, 30, tzinfo=UTC), "Vendredi 1 janvier 2027"),  # UTC -> Paris crosses midnight
    ],
)
def test_long_date(dt, expected):
    assert fmt.long_date(dt, TZ) == expected


def test_hour_range_both_separators_and_timezone_conversion():
    start, end = datetime(2026, 10, 8, 12, 5, tzinfo=UTC), datetime(2026, 10, 8, 13, 5, tzinfo=UTC)
    assert fmt.hour_range(start, end, TZ) == "14h05 - 15h05"
    assert fmt.hour_range(start, end, TZ, ":") == "14:05 - 15:05"
    # Winter time: UTC+1.
    assert fmt.hour_range(datetime(2026, 11, 2, 8, tzinfo=UTC), datetime(2026, 11, 2, 9, tzinfo=UTC), TZ, ":") == "09:00 - 10:00"


def test_short_date_is_zero_padded_in_local_time():
    assert fmt.short_date(datetime(2026, 3, 4, 23, 30, tzinfo=UTC), TZ) == "05/03/2026"


@pytest.mark.parametrize("n, expected", [(0, "0 heures"), (1, "1 heure"), (2, "2 heures"), (5, "5 heures")])
def test_hours_label(n, expected):
    assert fmt.hours(n) == expected


# --- templates ----------------------------------------------------------------------


def _confirmation(**over):
    ctx = dict(
        date_long="Jeudi 8 octobre 2026",
        hour_range="14h00 - 15h00",
        meet_url="https://meet.google.com/abc",
        hours_purchased_label="2 heures",
        hours_remaining=1,
        hours_remaining_label="1 heure",
        consultant_name="Suan Tay",
        first_session=True,
    )
    ctx.update(over)
    return render("customer_confirmation.txt", **ctx)


def test_customer_confirmation_singular_and_meet_link():
    body = _confirmation()
    assert "1 heure restera à programmer." in body
    assert "Lien visio :\nhttps://meet.google.com/abc" in body
    assert body.endswith("Suan Tay\nIAfluence\n")


def test_customer_confirmation_plural_and_without_meet():
    body = _confirmation(meet_url=None, hours_remaining=3, hours_remaining_label="3 heures")
    assert "3 heures resteront à programmer." in body
    assert "Lien visio" not in body


def test_templates_fail_loudly_on_missing_variables():
    with pytest.raises(UndefinedError):
        render("booking_link.txt", name="x")


# --- sending ------------------------------------------------------------------------


class _StubGmail:
    def __init__(self):
        self.sent = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.sent.append((userId, body))
        return self

    def execute(self):
        return {"id": "msg_1"}


def test_gmail_mailer_builds_utf8_message(monkeypatch):
    monkeypatch.setattr(email_service, "get_config", lambda: Config(mail_from="contact@iafluence.fr", mail_from_name="Suan Tay — IAfluence"))
    api = _StubGmail()
    GmailMailer(lambda: api).send("jean@proton.me", "Votre rendez-vous est confirmé", "Bonjour,\nÀ bientôt")
    [(user_id, body)] = api.sent
    assert user_id == "me"
    msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=policy.default)
    assert msg["To"] == "jean@proton.me"
    assert msg["Subject"] == "Votre rendez-vous est confirmé"
    assert msg["From"].addresses[0].addr_spec == "contact@iafluence.fr"
    assert msg["From"].addresses[0].display_name == "Suan Tay — IAfluence"
    assert msg.get_content() == "Bonjour,\nÀ bientôt\n"


def test_gmail_mailer_defaults_to_google_client_factory():
    from app.services import google_client

    assert GmailMailer()._api is google_client.gmail_api


class _RecordingMailer:
    def __init__(self, exc=None):
        self.sent, self.exc = [], exc

    def send(self, to, subject, body):
        if self.exc:
            raise self.exc
        self.sent.append((to, subject, body))


def test_send_safely_success():
    m = _RecordingMailer()
    assert send_safely(m, "a@b.fr", "S", "B") is True
    assert m.sent == [("a@b.fr", "S", "B")]


def test_send_safely_skips_missing_recipient(caplog):
    m = _RecordingMailer()
    assert send_safely(m, "", "Sujet", "B") is False
    assert m.sent == []
    assert "no recipient" in caplog.text


def test_send_safely_swallows_and_logs_failures(caplog):
    assert send_safely(_RecordingMailer(RuntimeError("quota")), "a@b.fr", "Sujet", "B") is False
    assert "email 'Sujet' to a@b.fr failed" in caplog.text


class _StubGmailDrafts:
    def __init__(self):
        self.created = []

    def users(self):
        return self

    def drafts(self):
        return self

    def create(self, userId, body):
        self.created.append((userId, body))
        return self

    def execute(self):
        return {"id": "draft_1"}


def test_gmail_mailer_creates_a_draft(monkeypatch):
    monkeypatch.setattr(email_service, "get_config", lambda: Config(mail_from="contact@iafluence.fr"))
    api = _StubGmailDrafts()
    GmailMailer(lambda: api).draft("jean@proton.me", "Prochaine session", "Bonjour")
    [(user_id, body)] = api.created
    assert user_id == "me"
    msg = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]), policy=policy.default)
    assert (msg["To"], msg["Subject"], msg.get_content()) == ("jean@proton.me", "Prochaine session", "Bonjour\n")


def test_send_safely_as_draft():
    class M(_RecordingMailer):
        def draft(self, to, subject, body):
            self.drafted = (to, subject, body)

    m = M()
    assert send_safely(m, "a@b.fr", "S", "B", as_draft=True) is True
    assert m.drafted == ("a@b.fr", "S", "B") and m.sent == []


def test_html_email_with_inline_image(monkeypatch):
    monkeypatch.setattr(email_service, "get_config", lambda: Config(mail_from="contact@iafluence.fr"))
    api = _StubGmailDrafts()
    GmailMailer(lambda: api).draft(
        "jean@proton.me", "Compte rendu", "Texte", html='<img src="cid:compte-rendu">', images={"compte-rendu": b"PNG"}
    )
    [(_, body)] = api.created
    msg = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]), policy=policy.default)
    assert msg.get_content_type() == "multipart/alternative"
    plain, related = msg.get_payload()
    assert (plain.get_content(), related.get_content_type()) == ("Texte\n", "multipart/related")
    html, png = related.get_payload()
    assert html.get_content() == '<img src="cid:compte-rendu">\n'
    assert (png.get_content_type(), png["Content-ID"], png.get_content()) == ("image/png", "<compte-rendu>", b"PNG")
    assert png.get_content_disposition() == "inline" and png.get_filename() == "compte-rendu.png"


def test_html_email_with_inline_image_is_sent(monkeypatch):
    monkeypatch.setattr(email_service, "get_config", lambda: Config(mail_from="contact@iafluence.fr"))
    api = _StubGmail()
    GmailMailer(lambda: api).send("jean@proton.me", "S", "T", html="<p>T</p>")
    [(_, body)] = api.sent
    msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=policy.default)
    # No image: a plain text/html alternative.
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_send_safely_passes_the_html_part_only_when_there_is_one():
    class M:
        def __init__(self):
            self.calls = []

        def send(self, to, subject, body, **parts):
            self.calls.append(parts)

        draft = send

    m = M()
    send_safely(m, "a@b.fr", "S", "B")
    send_safely(m, "a@b.fr", "S", "B", as_draft=True, html="<p>B</p>", images={"x": b"1"})
    assert m.calls == [{}, {"html": "<p>B</p>", "images": {"x": b"1"}}]


def test_html_templates_are_escaped_text_templates_are_not():
    assert email_service.render("session_report.html", **_report_ctx("<b>")).count("&lt;b&gt;") == 1
    assert "<b>" in email_service.render("session_report.txt", **_report_ctx("<b>"))


def _report_ctx(item):
    return {
        "name": "Jean",
        "date_long": "jeudi 8 octobre 2026",
        "sections": [("Décisions", [item])],
        "image_cid": None,
        "last": True,
        "hours_purchased_label": "1 heure",
        "hours_remaining_label": "0 heure",
        "booking_url": None,
        "shop_url": "https://iafluence.fr",
        "consultant_name": "Suan Tay",
    }
