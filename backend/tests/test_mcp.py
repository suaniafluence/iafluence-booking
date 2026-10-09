"""MCP server: a ChatGPT / Claude connector pastes a transcript and follows its report (real PostgreSQL)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import deps, main
from app.config import get_config
from app.db import SessionLocal
from app.models import Booking, SessionReport
from app.services import follow_up, session_reports
from app.services.session_reports import Gateways
from tests.conftest import NOW as CONFTEST_NOW
from tests.conftest import FakeCodex, paris
from tests.test_pasted_transcripts import DICTATION, speakers_answer

TOKEN = "t" * 40
URL = f"/api/mcp/{TOKEN}"
NOW = paris(2026, 10, 8, 17)


@pytest.fixture
def mcp(client, monkeypatch):
    monkeypatch.setattr(get_config(), "mcp_token", TOKEN)
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")
    main.app.dependency_overrides[deps.get_now] = lambda: NOW
    return client


def rpc(client, method, params=None, id_=1, url=URL, **kw):
    message = {"jsonrpc": "2.0", "method": method} | ({"id": id_} if id_ is not None else {})
    if params is not None:
        message["params"] = params
    return client.post(url, json=message, **kw)


def call(client, name, arguments):
    r = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def report() -> SessionReport:
    with SessionLocal() as db:
        return db.scalar(select(SessionReport))


# --- access ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["", "court"])
def test_off_without_a_long_enough_token(client, monkeypatch, token):
    monkeypatch.setattr(get_config(), "mcp_token", token)
    assert rpc(client, "ping", url=f"/api/mcp/{token or 'x'}").status_code == 404


def test_wrong_token_is_refused(mcp):
    assert rpc(mcp, "ping", url="/api/mcp/" + "u" * 40).status_code == 401
    assert rpc(mcp, "ping", url="/api/mcp").status_code == 401


def test_bearer_token_is_accepted(mcp):
    r = rpc(mcp, "ping", url="/api/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_no_event_stream(mcp):
    assert mcp.get(URL).status_code == 405


# --- protocol ----------------------------------------------------------------------------------------------------


def test_initialize_echoes_a_known_protocol_version(mcp):
    result = rpc(mcp, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}).json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "iafluence-comptes-rendus"
    assert "soumettre_transcription" in result["instructions"]
    assert rpc(mcp, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]["protocolVersion"] == "2025-11-25"


def test_notifications_get_no_body(mcp):
    r = rpc(mcp, "notifications/initialized", id_=None)
    assert (r.status_code, r.content) == (202, b"")


def test_tools_are_listed_with_their_schemas(mcp):
    tools = rpc(mcp, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["rendez_vous_termines", "soumettre_transcription", "etat_compte_rendu"]
    submit = tools[1]["inputSchema"]
    assert submit["required"] == ["texte"] and submit["additionalProperties"] is False


@pytest.mark.parametrize(
    "message,code",
    [({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, -32601), ({"id": 1, "method": "ping"}, -32600)],
)
def test_protocol_errors(mcp, message, code):
    assert mcp.post(URL, json=message).json()["error"]["code"] == code


def test_unreadable_json(mcp):
    r = mcp.post(URL, content=b"{", headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, -32700)


def test_unknown_tool(mcp):
    r = rpc(mcp, "tools/call", {"name": "envoyer_email", "arguments": {}})
    assert r.json()["error"]["code"] == -32602


# --- tools -------------------------------------------------------------------------------------------------------


def test_a_dictated_meeting_becomes_a_draft(mcp, fakes):
    result = call(
        mcp,
        "soumettre_transcription",
        {"texte": DICTATION, "nombre_interlocuteurs": 2, "nom": "Claire Martin", "email": "claire@exemple.fr", "duree_minutes": 45},
    )
    assert not result.get("isError"), result
    rep = report()
    assert result["structuredContent"]["report_id"] == rep.id
    assert (rep.status, rep.transcript_source, rep.speaker_hint) == ("summarizing", "pasted", {"nombre": 2, "noms": []})
    with SessionLocal() as db:
        booking = db.scalar(select(Booking))
        assert (booking.kind, booking.end_datetime, booking.start_datetime) == ("meeting", NOW, NOW - timedelta(minutes=45))

    fakes["codex"].answers = [speakers_answer([(1, 4, 1)]), FakeCodex.answer()]
    session_reports.process(Gateways(fakes["mailer"], fakes["fireflies"], fakes["codex"]), NOW)
    assert [m["to"] for m in fakes["mailer"].drafts] == ["claire@exemple.fr"]
    status = call(mcp, "etat_compte_rendu", {"report_id": rep.id})["structuredContent"]
    assert status["statut"] == "brouillon Gmail créé"
    assert status["synthese"]["points_abordes"] and status["interlocuteurs"][0]["nom"] == "Suan Tay"


def test_a_finished_session_is_listed_then_gets_its_transcript(mcp, fakes, token_for):
    token = token_for(hours=3, name="Marie Martin", email="marie@example.com")
    start = paris(2026, 10, 8, 14)
    main.app.dependency_overrides[deps.get_now] = lambda: CONFTEST_NOW
    assert mcp.post("/api/bookings", json={"token": token, "start": start.isoformat()}).status_code == 201
    main.app.dependency_overrides[deps.get_now] = lambda: NOW
    follow_up.process_finished_sessions(fakes["mailer"], start + timedelta(hours=1))

    [row] = call(mcp, "rendez_vous_termines", {})["structuredContent"]["rendez_vous"]
    assert (row["type"], row["client"], row["compte_rendu"], row["peut_recevoir_une_transcription"]) == (
        "séance", "Marie Martin", "aucun", True,
    )
    result = call(mcp, "soumettre_transcription", {"texte": DICTATION, "booking_id": row["booking_id"]})
    assert result["structuredContent"]["booking_id"] == row["booking_id"]
    [row] = call(mcp, "rendez_vous_termines", {"nombre": 5})["structuredContent"]["rendez_vous"]
    assert (row["compte_rendu"], row["peut_recevoir_une_transcription"]) == ("résumé en cours (quelques minutes)", False)


@pytest.mark.parametrize(
    "arguments,message",
    [
        ({"texte": DICTATION}, "Indiquez booking_id, ou bien le nom et l'email du destinataire."),
        ({"texte": "court", "nom": "A", "email": "a@b.fr"}, "La transcription est trop courte"),
        ({"texte": DICTATION, "booking_id": 999}, "Rendez-vous introuvable."),
        ({"texte": DICTATION, "email": "pas-un-email", "nom": "A"}, "Argument invalide (email)"),
        ({"texte": DICTATION, "inconnu": 1}, "Argument invalide (inconnu)"),
    ],
)
def test_tool_errors_are_shown_to_the_model(mcp, arguments, message):
    result = call(mcp, "soumettre_transcription", arguments)
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith(message)


def test_no_report_without_codex(mcp, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    result = call(mcp, "soumettre_transcription", {"texte": DICTATION, "nom": "A", "email": "a@b.fr"})
    assert result["isError"] and "Codex" in result["content"][0]["text"]


def test_unknown_report(mcp):
    assert call(mcp, "etat_compte_rendu", {"report_id": 42})["isError"] is True
