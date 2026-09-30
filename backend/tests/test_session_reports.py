"""Session reports: Fireflies transcript -> Codex summary -> Gmail draft (real PostgreSQL, fake Fireflies/Codex)."""

import asyncio
import email
import logging
from datetime import timedelta
from email import policy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from app import main
from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, BookingToken, Customer, Purchase, SessionReport, Settings
from app.services import follow_up, report_content, session_reports
from app.services.codex import CodexTurnFailed, CodexUnavailable
from app.services.email_service import build_message
from app.services.fireflies import FirefliesError, Sentence
from app.services.session_reports import Gateways
from tests.conftest import SYNTHESE, FakeCodex, paris

pytestmark = pytest.mark.usefixtures("db_clean")

SLOT = paris(2026, 10, 8, 14)
END = SLOT + timedelta(hours=1)
POLL = timedelta(minutes=5)
CLIENT = "marie@example.com"
TRANSCRIPT_SECRET = "mon code secret est 4242"


@pytest.fixture(autouse=True)
def reports_on(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(cfg, "fireflies_api_key", "ff-key")
    monkeypatch.setattr(cfg, "codex_app_server_url", "ws://codex:4500")
    monkeypatch.setattr(cfg, "fireflies_poll_seconds", 300)
    monkeypatch.setattr(cfg, "fireflies_max_wait_hours", 6)


@pytest.fixture
def gw(fakes):
    return Gateways(mailer=fakes["mailer"], fireflies=fakes["fireflies"], codex=fakes["codex"])


@pytest.fixture
def finished(client, fakes, token_for):
    """A 3 h client whose first session (SLOT) just ended; returns its booking token."""

    def _make(hours=3, start=SLOT):
        token = token_for(hours=hours, name="Marie Martin", email=CLIENT)
        r = client.post("/api/bookings", json={"token": token, "start": start.isoformat()})
        assert r.status_code == 201, r.text
        fakes["mailer"].sent.clear()
        assert follow_up.process_finished_sessions(fakes["mailer"], start + timedelta(hours=1)) == 1
        return token

    return _make


def report() -> SessionReport:
    with SessionLocal() as db:
        return db.scalar(select(SessionReport))


def record(fakes, start=SLOT + timedelta(minutes=2), emails=(CLIENT, "suan@iafluence.fr"), **kw):
    fakes["fireflies"].add("ff_1", start, emails, **kw)


def client_mails(fakes):
    mailer = fakes["mailer"]
    return [m for m in mailer.drafts + mailer.sent if m["to"] == CLIENT]


def alerts(fakes):
    return [m for m in fakes["mailer"].sent if m["subject"] == session_reports.ALERT_SUBJECT]


# --- creation --------------------------------------------------------------------------------------------------------


def test_end_of_session_waits_for_the_transcript_instead_of_emailing(finished, fakes, gw):
    finished()
    assert fakes["mailer"].drafts == [] and fakes["mailer"].sent == []
    r = report()
    assert (r.status, r.waiting_since, r.next_attempt_at, r.transcript_attempts) == ("waiting_transcript", END, END + POLL, 0)

    # Fireflies needs a few minutes: not asked before the first poll.
    session_reports.process(gw, END + POLL - timedelta(seconds=1))
    assert fakes["fireflies"].list_calls == []
    # The session is closed once: no second report.
    assert follow_up.process_finished_sessions(fakes["mailer"], END + POLL) == 0
    with SessionLocal() as db:
        assert db.scalar(select(text("count(*)")).select_from(SessionReport)) == 1


def test_without_fireflies_or_codex_the_v1_email_is_prepared_at_once(client, fakes, token_for, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    token = token_for(hours=3, email=CLIENT)
    client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 1
    assert [m["subject"] for m in fakes["mailer"].drafts] == [session_reports.SUBJECT_NEXT_V1]
    assert report() is None


def test_revoked_link_creates_no_report(client, fakes, token_for):
    token = token_for(hours=3, email=CLIENT)
    client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()})
    with SessionLocal() as db:
        db.execute(update(BookingToken).values(revoked_at=END))
        db.commit()
    assert follow_up.process_finished_sessions(fakes["mailer"], END) == 0
    assert report() is None


# --- happy path ------------------------------------------------------------------------------------------------------


def test_summary_is_drafted_with_the_infographic(finished, fakes, gw, caplog):
    token = finished()
    record(fakes, sentences=[("Suan", "Bonjour Marie"), ("Marie", TRANSCRIPT_SECRET)])

    with caplog.at_level(logging.DEBUG):
        session_reports.process(gw, END + POLL)

    # One Fireflies request covering the session start ± 15 min.
    assert fakes["fireflies"].list_calls == [(SLOT - timedelta(minutes=15), SLOT + timedelta(minutes=15))]
    r = report()
    assert (r.status, r.delivery, r.with_summary, r.drafted_at) == ("drafted", "draft", True, END + POLL)
    assert (r.fireflies_transcript_id, r.transcript_attempts, r.summary_attempts, r.error) == ("ff_1", 1, 1, None)
    assert r.summary == SYNTHESE and r.image_png.startswith(b"\x89PNG") and r.claimed_until is None

    [turn] = fakes["codex"].turns
    assert turn["instructions"] == report_content.agent_instructions()
    assert turn["output_schema"] == report_content.OUTPUT_SCHEMA
    assert '"seance_numero": 1' in turn["prompt"] and '"heures_restantes": 2' in turn["prompt"]
    assert '"derniere_seance": false' in turn["prompt"] and '"client": "Marie Martin"' in turn["prompt"]
    assert "Suan : Bonjour Marie\nMarie : " + TRANSCRIPT_SECRET in turn["prompt"]
    assert CLIENT not in turn["prompt"]  # the agent does not need the client's email

    [mail] = fakes["mailer"].drafts
    assert (mail["to"], mail["subject"]) == (CLIENT, session_reports.SUBJECT_NEXT)
    assert mail["body"] == (
        "Bonjour Marie Martin,\n\n"
        "Merci pour notre session de conseil IA du jeudi 8 octobre 2026. Voici son compte rendu.\n\n"
        "Objectifs\n- Cadrer le projet d'assistant\n\n"
        "Points abordés\n- Cas d'usage prioritaires\n- Choix de l'outil\n\n"
        "Décisions\n- Démarrer par les devis\n\n"
        "Vos actions\n- Rassembler dix devis\n\n"
        "Prochaines étapes\n- Prototype à la prochaine séance\n\n"
        "L'infographie de la séance est jointe à cet email.\n\n"
        "Il vous reste 2 heures de conseil. Vous pouvez dès maintenant choisir le créneau de votre prochaine "
        "session de 1 heure :\n\n"
        f"https://booking.iafluence.test/reservation/{token}\n\n"
        "À bientôt,\n\nSuan Tay\nIAfluence\n"
    )
    assert 'src="cid:compte-rendu"' in mail["html"] and "Choix de l&#39;outil" in mail["html"]
    assert f'href="https://booking.iafluence.test/reservation/{token}"' in mail["html"]
    assert list(mail["images"]) == ["compte-rendu"] and mail["images"]["compte-rendu"] == r.image_png
    assert fakes["mailer"].sent == []

    # RGPD: the transcript is neither stored nor logged.
    with SessionLocal() as db:
        row = db.execute(text("SELECT row_to_json(r)::text FROM session_reports r")).scalar()
    assert TRANSCRIPT_SECRET not in row and "Bonjour Marie" not in row
    assert TRANSCRIPT_SECRET not in caplog.text

    # Idempotent: nothing more on the next runs.
    session_reports.process(gw, END + 2 * POLL)
    assert len(fakes["mailer"].drafts) == 1 and len(fakes["codex"].turns) == 1


def test_html_email_escapes_generated_content(finished, fakes, gw):
    finished()
    record(fakes)
    fakes["codex"].answers = [FakeCodex.answer({**SYNTHESE, "decisions": ['<a href="https://evil">clic</a>']})]
    session_reports.process(gw, END + POLL)
    [mail] = fakes["mailer"].drafts
    assert "<a href=\"https://evil\">" not in mail["html"] and "&lt;a href=&#34;https://evil&#34;&gt;" in mail["html"]


def test_empty_sections_are_left_out(finished, fakes, gw):
    finished()
    record(fakes)
    fakes["codex"].answers = [FakeCodex.answer({**SYNTHESE, "decisions": [], "objectifs": []})]
    session_reports.process(gw, END + POLL)
    [mail] = fakes["mailer"].drafts
    assert "Décisions" not in mail["body"] and "Objectifs" not in mail["body"] and "Décisions" not in mail["html"]
    assert "Points abordés" in mail["body"]


def test_multipart_draft_carries_the_png_inline(finished, fakes, gw):
    finished()
    record(fakes)
    session_reports.process(gw, END + POLL)
    [mail] = fakes["mailer"].drafts
    msg = email.message_from_bytes(
        build_message(mail["to"], mail["subject"], mail["body"], html=mail["html"], images=mail["images"]).as_bytes(),
        policy=policy.default,
    )
    assert msg.get_content_type() == "multipart/alternative"
    plain, related = msg.get_payload()
    assert plain.get_content_type() == "text/plain" and related.get_content_type() == "multipart/related"
    html, png = related.get_payload()
    assert html.get_content_type() == "text/html" and png.get_content_type() == "image/png"
    assert png["Content-ID"] == "<compte-rendu>" and png.get_content() == report().image_png


def test_last_session_summary_points_to_the_shop(finished, fakes, gw):
    finished(hours=1)
    record(fakes)
    session_reports.process(gw, END + POLL)
    [mail] = fakes["mailer"].drafts
    assert mail["subject"] == session_reports.SUBJECT_LAST
    assert "Votre accompagnement (1 heure de conseil) est maintenant terminé." in mail["body"]
    assert "https://iafluence.fr\n" in mail["body"] and "reservation" not in mail["body"]
    assert '"derniere_seance": true' in fakes["codex"].turns[0]["prompt"]


def test_second_session_is_numbered_two(client, finished, fakes, gw):
    token = finished()
    record(fakes)
    session_reports.process(gw, END + POLL)
    nxt = paris(2026, 10, 9, 10)
    client.post("/api/bookings", json={"token": token, "start": nxt.isoformat()})
    follow_up.process_finished_sessions(fakes["mailer"], nxt + timedelta(hours=1))
    fakes["fireflies"].add("ff_2", nxt, [CLIENT])
    session_reports.process(gw, nxt + timedelta(hours=1) + POLL)
    assert '"seance_numero": 2' in fakes["codex"].turns[1]["prompt"]


# --- matching the recording ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start, emails, link, found",
    [
        (SLOT + timedelta(minutes=15), [CLIENT.upper()], None, True),
        (SLOT - timedelta(minutes=15), [CLIENT], None, True),
        (SLOT + timedelta(minutes=16), [CLIENT], None, False),
        (SLOT, ["autre@example.com"], None, False),
        (SLOT, ["autre@example.com"], "https://meet.google.com/abc-defg-hij?authuser=1", True),
        (SLOT, [], "https://meet.google.com/zzz-zzzz-zzz", False),
    ],
    ids=["+15min", "-15min", "+16min", "other-client", "meet-link", "other-meet"],
)
def test_recording_is_matched_on_start_and_client_or_meet(finished, fakes, gw, start, emails, link, found):
    finished()
    fakes["fireflies"].add("ff_1", start, emails, meeting_link=link)
    session_reports.process(gw, END + POLL)
    r = report()
    if found:
        assert (r.status, r.fireflies_transcript_id) == ("drafted", "ff_1")
    else:
        assert (r.status, r.fireflies_transcript_id, r.transcript_attempts) == ("waiting_transcript", None, 1)
        assert r.next_attempt_at == END + 2 * POLL


def test_closest_recording_wins_and_is_used_once(finished, fakes, gw):
    finished()
    fakes["fireflies"].add("ff_far", SLOT + timedelta(minutes=10), [CLIENT])
    fakes["fireflies"].add("ff_near", SLOT - timedelta(minutes=3), [CLIENT])
    session_reports.process(gw, END + POLL)
    assert report().fireflies_transcript_id == "ff_near"
    assert session_reports.match(report_booking(), fakes["fireflies"].recordings, {"ff_near"}).id == "ff_far"


def report_booking():
    with SessionLocal() as db:
        booking = db.scalar(select(Booking))
        booking.customer  # load before the session closes
        return booking


def test_recording_still_processing_is_retried(finished, fakes, gw):
    finished()
    record(fakes, sentences=[])
    session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.fireflies_transcript_id, r.next_attempt_at) == ("waiting_transcript", "ff_1", END + 2 * POLL)
    assert fakes["codex"].turns == []

    fakes["fireflies"].transcripts["ff_1"] = [Sentence("Suan", "Bonjour")]
    session_reports.process(gw, END + 2 * POLL)
    assert report().status == "drafted"


def test_fireflies_errors_are_retried_at_the_next_poll(finished, fakes, gw, caplog):
    finished()
    fakes["fireflies"].fail = FirefliesError("quota de l'API Fireflies atteint")
    with caplog.at_level(logging.WARNING):
        session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.transcript_attempts, r.error) == ("waiting_transcript", 1, "quota de l'API Fireflies atteint")
    assert r.next_attempt_at == END + 2 * POLL
    assert "Fireflies lookup failed for 1 session(s)" in caplog.text

    fakes["fireflies"].fail = None
    record(fakes)
    session_reports.process(gw, END + 2 * POLL)
    assert (report().status, report().error) == ("drafted", None)


def test_one_summary_per_cycle(client, fakes, gw, token_for):
    starts = [SLOT, paris(2026, 10, 8, 16)]
    for i, start in enumerate(starts):
        email = f"c{i}@example.com"
        token = token_for(f"cs_cycle_{i}", hours=2, email=email)
        assert client.post("/api/bookings", json={"token": token, "start": start.isoformat()}).status_code == 201
        fakes["fireflies"].add(f"ff_{i}", start, [email])
    ended = starts[1] + timedelta(hours=1)
    follow_up.process_finished_sessions(fakes["mailer"], ended)
    session_reports.process(gw, ended + POLL)
    with SessionLocal() as db:
        assert list(db.scalars(select(SessionReport.status).order_by(SessionReport.id))) == ["drafted", "summarizing"]
    session_reports.process(gw, ended + POLL + timedelta(minutes=1))
    with SessionLocal() as db:
        assert list(db.scalars(select(SessionReport.status).order_by(SessionReport.id))) == ["drafted", "drafted"]
    assert len(fakes["codex"].turns) == 2


def test_one_fireflies_request_for_all_waiting_sessions(client, fakes, gw, token_for):
    starts = [SLOT, paris(2026, 10, 8, 16)]
    for i, start in enumerate(starts):
        token = token_for(f"cs_multi_{i}", hours=2, email=f"c{i}@example.com")
        assert client.post("/api/bookings", json={"token": token, "start": start.isoformat()}).status_code == 201
    follow_up.process_finished_sessions(fakes["mailer"], starts[1] + timedelta(hours=1))
    session_reports.process(gw, starts[1] + timedelta(hours=1) + POLL)
    assert fakes["fireflies"].list_calls == [(starts[0] - timedelta(minutes=15), starts[1] + timedelta(minutes=15))]


def test_no_transcript_after_6_hours_falls_back_to_the_v1_email_and_alerts(finished, fakes, gw):
    token = finished()
    session_reports.process(gw, END + timedelta(hours=6) - timedelta(seconds=1))
    assert client_mails(fakes) == []
    session_reports.process(gw, END + timedelta(hours=6))
    r = report()
    assert (r.status, r.with_summary, r.delivery) == ("drafted", False, "draft")
    assert r.error == "Aucune transcription Fireflies au bout de 6 h."
    [mail] = fakes["mailer"].drafts
    assert mail["subject"] == session_reports.SUBJECT_NEXT_V1 and "html" not in mail
    assert f"https://booking.iafluence.test/reservation/{token}" in mail["body"].splitlines()
    [warn] = alerts(fakes)
    assert warn["to"] == "admin@iafluence.test"
    assert warn["body"] == (
        "Compte rendu de séance : action requise.\n\n"
        "Client :\nMarie Martin <marie@example.com>\n\n"
        "Séance :\n08/10/2026 14:00 - 15:00\n\n"
        "Problème :\nAucune transcription Fireflies au bout de 6 h.\n\n"
        "L'email a été préparé sans compte rendu.\n\n"
        "Administration :\nhttps://booking.iafluence.test/admin\n"
    )
    assert fakes["codex"].turns == []


def test_timeout_on_a_refunded_purchase_prepares_nothing(finished, fakes, gw):
    finished()
    with SessionLocal() as db:
        db.execute(update(Purchase).values(payment_status="refunded"))
        db.commit()
    session_reports.process(gw, END + timedelta(hours=6))
    assert (report().status, report().error) == ("failed", "Achat remboursé : aucun email préparé.")
    assert client_mails(fakes) == [] and alerts(fakes) == []


# --- summary failures ------------------------------------------------------------------------------------------------


def test_invalid_output_is_retried_once_with_the_reason(finished, fakes, gw):
    finished()
    record(fakes)
    fakes["codex"].answers = ["pas du JSON", FakeCodex.answer()]
    session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.summary_attempts) == ("drafted", 2)
    first, second = fakes["codex"].turns
    assert "refusée" not in first["prompt"]
    assert second["prompt"].endswith(
        "\nTa réponse précédente a été refusée : sortie Codex invalide (JSON illisible). "
        "Respecte exactement le format demandé.\n"
    )


@pytest.mark.parametrize(
    "answers, error",
    [
        (["{}", "{}"], "Résumé impossible : sortie Codex invalide (synthese : Field required)"),
        (
            [FakeCodex.answer(image='<svg viewBox="0 0 10 10"><image href="https://x/y.png"/></svg>')] * 2,
            "Résumé impossible : sortie Codex invalide (image : Value error, SVG refusé : élément interdit)",
        ),
        ([CodexTurnFailed("tour Codex failed : quota"), CodexUnavailable("injoignable")], "Résumé impossible : injoignable"),
    ],
    ids=["schema", "svg", "codex-errors"],
)
def test_two_failed_attempts_fail_the_report_and_alert(finished, fakes, gw, answers, error):
    finished()
    record(fakes)
    fakes["codex"].answers = list(answers)
    session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.summary_attempts, r.error, r.claimed_until) == ("failed", 2, error, None)
    assert client_mails(fakes) == []
    [warn] = alerts(fakes)
    assert f"Problème :\n{error}\n\n{session_reports.RETRY_HINT}\n" in warn["body"]
    # Nothing more happens by itself.
    session_reports.process(gw, END + 2 * POLL)
    assert len(fakes["codex"].turns) == 2


def test_codex_not_connected_fails_at_once(finished, fakes, gw):
    finished()
    record(fakes)
    fakes["codex"].connected = None
    session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.summary_attempts, r.error) == ("failed", 1, "Codex n'est pas connecté.")
    [warn] = alerts(fakes)
    assert "Connectez Codex dans l'admin, puis cliquez sur « Relancer »." in warn["body"]


def test_unrenderable_svg_counts_as_invalid(finished, fakes, gw, monkeypatch):
    finished()
    record(fakes)

    def boom(svg):
        raise report_content.InvalidOutput("infographie SVG impossible à convertir en PNG")

    monkeypatch.setattr(report_content, "render_png", boom)
    session_reports.process(gw, END + POLL)
    assert report().error == "Résumé impossible : infographie SVG impossible à convertir en PNG"


def test_transcript_read_errors_wait_then_fail_after_6_hours(finished, fakes, gw):
    finished()
    record(fakes)
    fakes["fireflies"].fail_sentences = FirefliesError("Fireflies injoignable (ConnectError)")
    session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.error, r.next_attempt_at, r.claimed_until) == (
        "summarizing",
        "Fireflies injoignable (ConnectError)",
        END + 2 * POLL,
        None,
    )
    # Not claimed again before the next poll.
    session_reports.process(gw, END + POLL + timedelta(minutes=1))
    assert report().next_attempt_at == END + 2 * POLL

    session_reports.process(gw, END + timedelta(hours=6))
    r = report()
    assert (r.status, r.error) == ("failed", "Transcription Fireflies illisible : Fireflies injoignable (ConnectError)")
    assert len(alerts(fakes)) == 1 and fakes["codex"].turns == []


# --- delivery rules --------------------------------------------------------------------------------------------------


def set_auto_send(value: bool):
    with SessionLocal() as db:
        db.execute(update(Customer).values(auto_send_next_link=value))
        db.commit()


def test_auto_send_client_still_gets_a_draft_when_there_is_a_summary(finished, fakes, gw):
    finished()
    set_auto_send(True)
    record(fakes)
    session_reports.process(gw, END + POLL)
    assert [m["subject"] for m in fakes["mailer"].drafts] == [session_reports.SUBJECT_NEXT]
    assert fakes["mailer"].sent == [] and report().delivery == "draft"


def test_summaries_are_sent_without_review_when_the_admin_opted_in(finished, fakes, gw):
    finished()
    set_auto_send(True)
    with SessionLocal() as db:
        db.execute(update(Settings).values(send_reports_without_review=True))
        db.commit()
    record(fakes)
    session_reports.process(gw, END + POLL)
    [mail] = fakes["mailer"].sent
    assert mail["subject"] == session_reports.SUBJECT_NEXT and mail["images"]
    assert fakes["mailer"].drafts == [] and report().delivery == "sent"


def test_opt_in_alone_does_not_send_for_draft_clients(finished, fakes, gw):
    finished()
    with SessionLocal() as db:
        db.execute(update(Settings).values(send_reports_without_review=True))
        db.commit()
    record(fakes)
    session_reports.process(gw, END + POLL)
    assert len(fakes["mailer"].drafts) == 1 and fakes["mailer"].sent == []


def test_fallback_without_summary_follows_the_v1_auto_send_rule(finished, fakes, gw):
    finished()
    set_auto_send(True)
    session_reports.process(gw, END + timedelta(hours=6))
    assert [m["subject"] for m in client_mails(fakes)] == [session_reports.SUBJECT_NEXT_V1]
    assert fakes["mailer"].drafts == [] and report().delivery == "sent"


@pytest.mark.parametrize("change, error", [
    ("refund", "Achat remboursé : aucun email préparé."),
    ("revoke", "Lien de réservation révoqué : aucun email préparé."),
])
def test_no_email_when_the_purchase_changed_meanwhile(finished, fakes, gw, change, error):
    finished()
    with SessionLocal() as db:
        if change == "refund":
            db.execute(update(Purchase).values(payment_status="refunded"))
        else:
            db.execute(update(BookingToken).values(revoked_at=END))
        db.commit()
    record(fakes)
    session_reports.process(gw, END + POLL)
    assert (report().status, report().error) == ("failed", error)
    assert client_mails(fakes) == []


def test_gmail_failure_is_shown_on_the_report(finished, fakes, gw):
    finished()
    record(fakes)
    fakes["mailer"].fail = True
    session_reports.process(gw, END + POLL)
    r = report()
    assert (r.status, r.error) == ("drafted", "L'email n'a pas pu être préparé dans Gmail (voir les logs de l'API).")


# --- concurrency -----------------------------------------------------------------------------------------------------


def test_a_claimed_report_is_left_to_its_process_until_the_claim_expires(finished, fakes, gw):
    finished()
    record(fakes)
    claim_until = END + timedelta(minutes=20)
    with SessionLocal() as db:
        db.execute(
            update(SessionReport).values(
                status="summarizing", fireflies_transcript_id="ff_1", next_attempt_at=END, claimed_until=claim_until
            )
        )
        db.commit()
    session_reports.process(gw, claim_until - timedelta(seconds=1))
    assert fakes["codex"].turns == [] and report().status == "summarizing"
    # The process died: the claim expires and another one takes over.
    session_reports.process(gw, claim_until + timedelta(seconds=1))
    assert report().status == "drafted" and len(fakes["mailer"].drafts) == 1


def test_claim_lasts_the_codex_timeout_plus_a_margin(finished, fakes, gw, monkeypatch):
    finished()
    record(fakes)
    seen = []

    def run_turn(**kw):
        seen.append(report().claimed_until)
        return FakeCodex.answer()

    monkeypatch.setattr(fakes["codex"], "run_turn", run_turn)
    session_reports.process(gw, END + POLL)
    assert seen == [END + POLL + timedelta(seconds=600) + timedelta(minutes=5)]


def test_outcome_is_dropped_if_the_admin_drafted_meanwhile(finished, fakes, gw, monkeypatch):
    finished()
    record(fakes)

    def run_turn(**kw):
        with SessionLocal() as db:
            db.execute(update(SessionReport).values(status="drafted"))
            db.commit()
        return FakeCodex.answer()

    monkeypatch.setattr(fakes["codex"], "run_turn", run_turn)
    session_reports.process(gw, END + POLL)
    assert report().summary is None and client_mails(fakes) == []


def test_waiting_rows_locked_by_another_process_are_skipped(finished, fakes, gw):
    finished()
    record(fakes)
    with SessionLocal() as other:
        other.scalar(select(SessionReport).with_for_update())
        session_reports.process(gw, END + POLL)
        assert fakes["fireflies"].list_calls == []
        other.rollback()
    session_reports.process(gw, END + POLL)
    assert report().status == "drafted"


# --- retention -------------------------------------------------------------------------------------------------------


def test_summary_and_image_are_erased_after_the_retention_period(finished, fakes, gw, monkeypatch):
    finished()
    record(fakes)
    session_reports.process(gw, END + POLL)
    created = report().created_at
    session_reports.erase_expired(created + timedelta(days=90))
    assert report().summary is not None
    session_reports.erase_expired(created + timedelta(days=90, seconds=1))
    r = report()
    assert (r.summary, r.image_png, r.erased_at, r.status) == (None, None, created + timedelta(days=90, seconds=1), "drafted")

    monkeypatch.setattr(get_config(), "report_retention_days", 0)
    with SessionLocal() as db:
        db.execute(update(SessionReport).values(summary=SYNTHESE, erased_at=None))
        db.commit()
    session_reports.erase_expired(created + timedelta(days=900))
    assert report().summary == SYNTHESE


def test_reports_still_in_progress_are_not_erased(finished, fakes):
    finished()
    with SessionLocal() as db:
        db.execute(update(SessionReport).values(summary=SYNTHESE))
        db.commit()
    session_reports.erase_expired(report().created_at + timedelta(days=365))
    assert report().summary == SYNTHESE and report().erased_at is None


# --- background loop -------------------------------------------------------------------------------------------------


def test_loop_keeps_running_after_a_failure(monkeypatch, caplog):
    calls = []

    def fake(gw, now):
        calls.append((gw, now))
        if len(calls) == 1:
            raise RuntimeError("db down")
        if len(calls) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(session_reports, "process", fake)
    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        asyncio.run(session_reports.run_forever(lambda: "gw", 0, lambda: END))
    assert calls == [("gw", END)] * 3
    assert "session report job failed" in caplog.text


def test_loop_starts_with_the_app_only_when_reports_are_on(monkeypatch):
    started = []

    async def fake_run_forever(factory, interval, clock):
        started.append((interval, factory(), clock().tzinfo is not None))
        await asyncio.Event().wait()

    async def idle(*a):
        await asyncio.Event().wait()

    monkeypatch.setattr(session_reports, "run_forever", fake_run_forever)
    monkeypatch.setattr(follow_up, "run_forever", idle)
    monkeypatch.setattr(get_config(), "follow_up_poll_seconds", 60)
    with TestClient(main.app):
        pass
    [(interval, gateways, aware)] = started
    assert interval == 60 and aware and isinstance(gateways, Gateways)

    started.clear()
    monkeypatch.setattr(get_config(), "fireflies_api_key", "")
    with TestClient(main.app):
        pass
    assert started == []


def test_demo_integrations_run_the_whole_pipeline(finished, fakes):
    from app.dev_fakes import DemoCodex, DemoFireflies

    finished()
    codex = DemoCodex()
    codex.connected = True
    session_reports.process(Gateways(fakes["mailer"], DemoFireflies(), codex), END + POLL)
    r = report()
    assert (r.status, r.fireflies_transcript_id, r.with_summary) == ("drafted", "demo_1", True)
    [mail] = fakes["mailer"].drafts
    assert "Séance n° 1 — Marie Martin" not in mail["body"] and mail["images"]["compte-rendu"] == r.image_png
    assert "Rassembler dix exemples de devis représentatifs" in mail["body"]
