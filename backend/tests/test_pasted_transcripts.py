"""Transcripts pasted by the consultant: speakers attributed by Codex, then the usual summary and Gmail draft
(real PostgreSQL for the API tests, fake Codex)."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app import deps, main
from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, SessionReport
from app.services import follow_up, pasted_transcripts, session_reports
from app.services.pasted_transcripts import SpeakersOutput
from app.services.report_content import InvalidOutput
from app.services.session_reports import Gateways
from tests.conftest import NOW, FakeCodex, paris, staff_login

SLOT = paris(2026, 10, 8, 14)
LATER = SLOT + timedelta(hours=2)
CLIENT = "marie@example.com"
# What a phone dictation gives: no speaker name, one sentence after the other.
DICTATION = (
    "Bonjour Marie, je suis Suan, on fait le point sur vos devis. "
    "Bonjour, oui, je passe deux heures par jour sur les devis. "
    "Quels outils utilisez-vous aujourd'hui ? "
    "Un tableur et Word, rien de plus, et je recopie tout à la main pour chaque client."
)


def speakers_answer(turns, names=("Suan Tay", "Marie Martin")) -> str:
    return json.dumps(
        {
            "interlocuteurs": [{"nom": n, "role": "Consultant" if i == 0 else "Cliente"} for i, n in enumerate(names)],
            "tours": [{"debut": a, "fin": b, "interlocuteur": who} for a, b, who in turns],
        }
    )


ALTERNATING = speakers_answer([(1, 1, 1), (2, 2, 2), (3, 3, 1), (4, 4, 2)])


# --- segments and attribution (no database) ----------------------------------------------------------------------


def test_text_is_cut_into_sentences_and_lines():
    assert pasted_transcripts.segments("Bonjour. Ça va ?\n\n  Oui merci !  Et vous…  Bien\n") == [
        "Bonjour.", "Ça va ?", "Oui merci !", "Et vous…", "Bien",
    ]


def test_a_dictation_without_punctuation_is_cut_between_words():
    parts = pasted_transcripts.segments(" ".join(["mot"] * 400))
    assert len(parts) == 3 and all(len(p) <= pasted_transcripts.MAX_SEGMENT_CHARS for p in parts)
    assert " ".join(parts) == " ".join(["mot"] * 400)


def test_a_very_long_transcript_is_grouped_into_fewer_segments(monkeypatch):
    monkeypatch.setattr(pasted_transcripts, "MAX_SEGMENTS", 4)
    assert pasted_transcripts.segments("Un. Deux. Trois. Quatre. Cinq. Six.") == ["Un. Deux.", "Trois. Quatre.", "Cinq. Six."]


def output(turns, names=("Suan", "Marie")) -> SpeakersOutput:
    return pasted_transcripts.parse_output(speakers_answer(turns, names), 4, None)


def test_turns_become_one_line_per_speaker_change():
    lines = pasted_transcripts.attribute(["A.", "B.", "C.", "D."], output([(1, 2, 1), (3, 4, 2)]))
    assert lines == ["Suan : A. B.", "Marie : C. D."]


def test_segments_left_out_keep_the_previous_speaker():
    lines = pasted_transcripts.attribute(["A.", "B.", "C.", "D."], output([(2, 2, 1), (4, 4, 2)]))
    assert lines == [f"{pasted_transcripts.UNKNOWN_SPEAKER} : A.", "Suan : B. C.", "Marie : D."]


@pytest.mark.parametrize(
    "turns,hint,reason",
    [
        ([(1, 5, 1)], None, "hors limites"),
        ([(0, 2, 1)], None, "hors limites"),
        ([(3, 2, 1)], None, "hors limites"),
        ([(1, 4, 3)], None, "interlocuteur 3 inconnu"),
        ([(1, 4, 1)], {"nombre": 1}, "2 interlocuteurs pour 1 annoncés"),
    ],
)
def test_invalid_attributions_are_refused(turns, hint, reason):
    with pytest.raises(InvalidOutput, match=reason):
        pasted_transcripts.parse_output(speakers_answer(turns), 4, hint)


def test_prompt_numbers_the_segments_and_carries_what_was_announced():
    prompt = pasted_transcripts.build_prompt({"client": "Marie"}, {"nombre": 2, "noms": []}, ["A.", "B."])
    assert '"interlocuteurs_annonces": {\n    "nombre": 2\n  }' in prompt
    assert "<<<SEGMENTS\n[1] A.\n[2] B.\nSEGMENTS>>>" in prompt


# --- API and pipeline --------------------------------------------------------------------------------------------


@pytest.fixture
def codex_on(monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")
    # No Fireflies: pasting needs only Codex.
    monkeypatch.setattr(get_config(), "fireflies_api_key", "")


@pytest.fixture
def consultant(client, codex_on):
    staff_login(client)
    main.app.dependency_overrides[deps.get_now] = lambda: LATER
    return client


@pytest.fixture
def gw(fakes):
    return Gateways(mailer=fakes["mailer"], fireflies=fakes["fireflies"], codex=fakes["codex"])


@pytest.fixture
def session(client, fakes, token_for, codex_on):
    """A finished paid session, closed without a report (Fireflies is not connected); returns its booking id."""
    token = token_for(hours=3, name="Marie Martin", email=CLIENT)
    # Booked beforehand, whatever the clock of the test.
    later = main.app.dependency_overrides[deps.get_now]
    main.app.dependency_overrides[deps.get_now] = lambda: NOW
    assert client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()}).status_code == 201
    main.app.dependency_overrides[deps.get_now] = later
    follow_up.process_finished_sessions(fakes["mailer"], SLOT + timedelta(hours=1))
    fakes["mailer"].sent.clear()
    fakes["mailer"].drafts.clear()
    with SessionLocal() as db:
        return db.scalar(select(Booking.id))


def report() -> SessionReport:
    with SessionLocal() as db:
        return db.scalar(select(SessionReport))


def paste(consultant, booking_id, **kw):
    body = {"text": DICTATION, "speaker_count": 2, "speaker_names": ["Suan Tay", " "]} | kw
    return consultant.post(f"/api/consultant/bookings/{booking_id}/transcript", json=body)


def test_pasted_session_is_attributed_then_summarized_and_drafted(consultant, session, fakes, gw):
    r = paste(consultant, session)
    assert r.status_code == 201, r.text
    rep = report()
    assert r.json() == {"report_id": rep.id, "booking_id": session}
    assert (rep.status, rep.transcript_source, rep.speaker_hint) == ("summarizing", "pasted", {"nombre": 2, "noms": ["Suan Tay"]})

    fakes["codex"].answers = [ALTERNATING, FakeCodex.answer()]
    session_reports.process(gw, LATER)
    speakers_turn, summary_turn = fakes["codex"].turns
    assert "Agent « attribution des interlocuteurs »" in speakers_turn["instructions"]
    assert speakers_turn["output_schema"] is pasted_transcripts.OUTPUT_SCHEMA
    assert "[2] Bonjour, oui, je passe deux heures par jour sur les devis." in speakers_turn["prompt"]
    assert '"noms": [\n      "Suan Tay"\n    ]' in speakers_turn["prompt"]
    assert "Transcription collée (données à résumer" in summary_turn["prompt"]
    assert "Marie Martin : Bonjour, oui, je passe deux heures par jour sur les devis." in summary_turn["prompt"]
    assert '"seance_numero": 1' in summary_turn["prompt"]

    rep = report()
    assert (rep.status, rep.delivery, rep.with_summary) == ("drafted", "draft", True)
    # The text is not kept once the summary is written.
    assert rep.pasted_transcript is None
    assert rep.speakers == [{"nom": "Suan Tay", "role": "Consultant"}, {"nom": "Marie Martin", "role": "Cliente"}]
    [draft] = fakes["mailer"].drafts
    assert draft["to"] == CLIENT and draft["images"]

    [row] = consultant.get("/api/consultant/overview").json()["reports"]["sessions"]
    assert (row["report"]["source"], row["report"]["transcript_found"]) == ("pasted", True)
    assert [s["nom"] for s in row["report"]["speakers"]] == ["Suan Tay", "Marie Martin"]


def test_a_retry_after_a_failed_summary_skips_the_attribution(consultant, session, fakes, gw):
    paste(consultant, session)
    fakes["codex"].answers = [ALTERNATING, "pas du JSON", "toujours pas"]
    session_reports.process(gw, LATER)
    rep = report()
    assert (rep.status, len(fakes["codex"].turns)) == ("failed", 3)
    # The attributed lines replaced the pasted text, for « Relancer ».
    assert rep.pasted_transcript.splitlines()[1].startswith("Marie Martin : Bonjour, oui")

    assert consultant.post(f"/api/consultant/reports/{rep.id}/retry").json()["status"] == "summarizing"
    fakes["codex"].turns.clear()
    session_reports.process(gw, LATER + timedelta(minutes=1))
    [turn] = fakes["codex"].turns
    assert "Marie Martin : Bonjour, oui" in turn["prompt"]
    assert report().status == "drafted"


def test_attribution_refused_twice_fails_the_report_and_keeps_the_text(consultant, session, fakes, gw):
    paste(consultant, session)
    bad = speakers_answer([(1, 9, 1)])
    fakes["codex"].answers = [bad, bad]
    session_reports.process(gw, LATER)
    rep = report()
    assert rep.status == "failed"
    assert rep.error.startswith("Interlocuteurs impossibles à attribuer : plage de segments hors limites")
    assert rep.pasted_transcript == DICTATION and rep.speakers is None
    assert "Ta réponse précédente a été refusée" in fakes["codex"].turns[1]["prompt"]
    [alert] = fakes["mailer"].sent
    assert alert["subject"] == session_reports.ALERT_SUBJECT


def test_codex_not_connected(consultant, session, fakes, gw):
    paste(consultant, session)
    fakes["codex"].connected = None
    session_reports.process(gw, LATER)
    assert (report().status, report().error) == ("failed", "Codex n'est pas connecté.")


def test_two_turns_are_claimed_before_the_attribution(consultant, session, fakes, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_turn_timeout_seconds", 600)
    paste(consultant, session)
    session_reports._claim(LATER)
    assert report().claimed_until == LATER + timedelta(minutes=20) + session_reports.CLAIM_MARGIN


def test_a_session_waiting_for_fireflies_can_get_a_pasted_transcript(consultant, session, fakes, gw):
    with SessionLocal() as db:
        db.add(SessionReport(booking_id=session, status="waiting_transcript", waiting_since=LATER, error="x"))
        db.commit()
    assert paste(consultant, session).status_code == 201
    rep = report()
    assert (rep.status, rep.error, rep.transcript_source) == ("summarizing", None, "pasted")


@pytest.mark.parametrize("status", ["drafted", "ready"])
def test_no_paste_once_the_email_is_prepared(consultant, session, status):
    with SessionLocal() as db:
        db.add(SessionReport(booking_id=session, status=status, waiting_since=LATER))
        db.commit()
    r = paste(consultant, session)
    assert (r.status_code, r.json()["detail"]) == (409, "L'email de ce rendez-vous a déjà été préparé.")


def test_no_paste_while_a_summary_is_being_written(consultant, session):
    with SessionLocal() as db:
        db.add(SessionReport(booking_id=session, status="summarizing", waiting_since=LATER, claimed_until=LATER + timedelta(minutes=5)))
        db.commit()
    assert paste(consultant, session).status_code == 409


def test_unfinished_or_unknown_booking(consultant, session):
    with SessionLocal() as db:
        db.execute(update(Booking).values(status="confirmed"))
        db.commit()
    r = paste(consultant, session)
    assert (r.status_code, r.json()["detail"]) == (409, "Ce rendez-vous n'est pas terminé.")
    assert paste(consultant, session + 1000).status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"text": "trop court"}, {"speaker_count": 0}, {"speaker_count": 11}, {"speaker_names": ["x" * 81]}],
)
def test_invalid_pastes(consultant, session, body):
    assert paste(consultant, session, **body).status_code == 422


def test_pasting_needs_codex(consultant, session, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    r = paste(consultant, session)
    assert (r.status_code, r.json()["detail"]) == (409, "Connectez d'abord Codex.")
    overview = consultant.get("/api/consultant/overview").json()["reports"]
    assert overview["paste_enabled"] is False


def test_consultant_only(client, session):
    assert client.post(f"/api/consultant/bookings/{session}/transcript", json={}).status_code == 401
    assert client.post("/api/consultant/meetings/pasted", json={}).status_code == 401


def meeting(consultant, **kw):
    body = {
        "text": DICTATION,
        "title": "Rendez-vous au salon",
        "start": paris(2026, 10, 8, 10).isoformat(),
        "end": paris(2026, 10, 8, 11).isoformat(),
        "name": "Claire Martin",
        "email": "Claire@Exemple.fr",
        "locale": "es",
    } | kw
    return consultant.post("/api/consultant/meetings/pasted", json=body)


def test_pasted_meeting_is_summarized_as_a_draft(consultant, fakes, gw):
    r = meeting(consultant)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        booking = db.scalar(select(Booking))
        assert (booking.kind, booking.status, booking.title, booking.locale) == ("meeting", "completed", "Rendez-vous au salon", "es")
        assert booking.customer.email == "claire@exemple.fr"
    fakes["codex"].answers = [speakers_answer([(1, 4, 1)], ("Claire Martin",)), FakeCodex.answer()]
    session_reports.process(gw, LATER)
    assert '"type_rdv": "reunion"' in fakes["codex"].turns[0]["prompt"]
    [draft] = fakes["mailer"].drafts
    assert draft["to"] == "claire@exemple.fr"
    assert report().status == "drafted"


def test_pasted_meeting_must_end_after_it_starts(consultant):
    r = meeting(consultant, end=paris(2026, 10, 8, 10).isoformat())
    assert (r.status_code, r.json()["detail"]) == (422, "La fin de la réunion doit être après son début.")


def test_pasted_text_is_erased_after_the_retention_period(consultant, session, fakes, gw, monkeypatch):
    monkeypatch.setattr(get_config(), "report_retention_days", 90)
    paste(consultant, session)
    fakes["codex"].answers = [speakers_answer([(1, 9, 1)])] * 2
    session_reports.process(gw, LATER)
    with SessionLocal() as db:
        db.execute(update(SessionReport).values(created_at=LATER - timedelta(days=91)))
        db.commit()
    session_reports.erase_expired(LATER)
    assert report().pasted_transcript is None and report().erased_at == LATER


def test_an_erased_paste_asks_to_paste_again(consultant, session, fakes, gw):
    paste(consultant, session)
    with SessionLocal() as db:
        db.execute(update(SessionReport).values(pasted_transcript=None))
        db.commit()
    session_reports.process(gw, LATER)
    assert (report().status, report().error) == ("failed", "Transcription collée effacée.")


def test_demo_integrations_attribute_the_speakers(consultant, session, fakes, gw, monkeypatch):
    from app.dev_fakes import DemoCodex

    codex = DemoCodex()
    codex.connected = True
    paste(consultant, session, speaker_names=[])
    session_reports.process(Gateways(mailer=fakes["mailer"], fireflies=fakes["fireflies"], codex=codex), LATER)
    rep = report()
    assert rep.status == "drafted"
    assert [s["nom"] for s in rep.speakers] == ["Suan Tay", "Marie Martin"]
