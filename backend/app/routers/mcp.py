"""MCP server (Model Context Protocol, Streamable HTTP) for a ChatGPT or Claude connector.

The consultant dictates or records a conversation in ChatGPT (microphone, voice mode, meeting recording), or
pastes one from the phone, then asks the assistant to send it here: the transcript goes through the same pipeline
as one pasted in the cockpit (speakers attributed by Codex, summary, Gmail draft to review). The assistant never
sends an email: it only queues a report.

Stateless JSON-RPC: every request is one POST answered with one JSON response, no session and no SSE stream.
Access: the URL carries MCP_TOKEN (connectors of ChatGPT and claude.ai take a URL, not a custom header), or a client
sends it as a bearer token to /api/mcp. The token is a credential: it is never logged.
"""

import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_config
from app.db import get_db
from app.deps import get_now
from app.models import SessionReport
from app.services import pasted_transcripts, session_reports
from app.services.settings_service import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp")

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MIN_TOKEN_CHARS = 32
SERVER_INFO = {"name": "iafluence-comptes-rendus", "title": "IAfluence — comptes rendus", "version": "1.0"}
INSTRUCTIONS = (
    "Outils du cabinet IAfluence pour les comptes rendus de rendez-vous. Quand l'utilisateur te donne (ou dicte) la "
    "transcription d'une conversation, envoie-la telle quelle avec `soumettre_transcription`, sans la résumer ni la "
    "corriger : le serveur attribue les interlocuteurs, rédige le compte rendu et le prépare en brouillon Gmail à "
    "relire. Demande combien de personnes parlaient et leurs noms si tu ne les connais pas. Pour un rendez-vous "
    "réservé sur le site, retrouve-le d'abord avec `rendez_vous_termines`."
)

Text = Annotated[str, StringConstraints(max_length=pasted_transcripts.MAX_CHARS)]
SpeakerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: Annotated[int, Field(ge=1, le=30, description="Nombre de rendez-vous, les plus récents d'abord")] = 10


class SubmitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texte: Text = Field(description="Transcription complète, telle quelle (sans résumé ni correction)")
    nombre_interlocuteurs: Annotated[int, Field(ge=1, le=10)] | None = Field(
        None, description="Nombre de personnes qui parlent, s'il est connu"
    )
    noms_interlocuteurs: Annotated[list[SpeakerName], Field(max_length=10)] = Field(
        default_factory=list, description="Noms des personnes qui parlent, s'ils sont connus"
    )
    booking_id: int | None = Field(
        None, description="Rendez-vous réservé sur le site (voir rendez_vous_termines). Sinon : nom et email."
    )
    nom: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = Field(
        None, description="Destinataire du compte rendu (réunion hors réservation)"
    )
    email: EmailStr | None = Field(None, description="Email du destinataire (réunion hors réservation)")
    titre: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    langue: Literal["fr", "en", "es"] = Field("fr", description="Langue du compte rendu")
    debut: AwareDatetime | None = Field(None, description="Début de la réunion (ISO 8601). Défaut : il y a `duree_minutes`.")
    duree_minutes: Annotated[int, Field(ge=5, le=600)] = 60


class StatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int


def _schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


TOOLS = [
    {
        "name": "rendez_vous_termines",
        "title": "Rendez-vous terminés",
        "description": "Séances, appels découverte et réunions terminés, les plus récents d'abord, avec l'état de "
        "leur compte rendu et s'il est possible d'y joindre une transcription.",
        "inputSchema": _schema(ListArgs),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "soumettre_transcription",
        "title": "Soumettre une transcription",
        "description": "Envoie la transcription d'une conversation (sans noms d'interlocuteurs) pour un compte rendu : "
        "les interlocuteurs sont attribués d'après le sens, puis le compte rendu est rédigé et préparé en brouillon "
        "Gmail à relire (rien n'est envoyé au client). Pour un rendez-vous réservé : booking_id. Sinon : nom et email "
        "du destinataire.",
        "inputSchema": _schema(SubmitArgs),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    },
    {
        "name": "etat_compte_rendu",
        "title": "État d'un compte rendu",
        "description": "Où en est un compte rendu demandé : en cours, prêt (synthèse), brouillon créé, ou échec.",
        "inputSchema": _schema(StatusArgs),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

STATUS_LABELS = {
    "waiting_transcript": "en attente de la transcription Fireflies",
    "summarizing": "résumé en cours (quelques minutes)",
    "ready": "résumé prêt, brouillon en préparation",
    "drafted": "brouillon Gmail créé",
    "failed": "échec",
}


class ToolError(Exception):
    """Shown to the model as the tool result (isError), so it can tell the user or fix its call."""


def check_token(request: Request, token: str | None) -> None:
    expected = get_config().mcp_token
    if len(expected) < MIN_TOKEN_CHARS:
        raise HTTPException(404)
    if token is None:
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth[:7].lower() == "bearer " else ""
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, "Jeton MCP invalide.")


# --- tools -------------------------------------------------------------------------------------------------------


def list_finished(db: Session, args: ListArgs, now: datetime) -> dict:
    tz = ZoneInfo(get_settings(db).timezone)
    out = []
    for s in session_reports.overview(db, tz, limit=args.nombre):
        r = s["report"]
        out.append(
            {
                "booking_id": s["booking_id"],
                "type": {"session": "séance", "discovery": "appel découverte", "meeting": "réunion"}[s["kind"]],
                "client": s["customer"],
                "email": s["email"],
                "prestation": s["product"],
                "debut": s["start"],
                "compte_rendu": STATUS_LABELS[r["status"]] if r else "aucun",
                "peut_recevoir_une_transcription": r is None or r["status"] in ("waiting_transcript", "failed"),
            }
        )
    return {"rendez_vous": out}


def submit(db: Session, args: SubmitArgs, now: datetime) -> dict:
    if not pasted_transcripts.enabled():
        raise ToolError("Codex n'est pas configuré sur le serveur : aucun compte rendu possible.")
    hint = pasted_transcripts.hint_of(args.nombre_interlocuteurs, args.noms_interlocuteurs)
    try:
        if args.booking_id is not None:
            report = pasted_transcripts.attach(db, args.booking_id, args.texte, hint, now)
        else:
            if not (args.nom and args.email):
                raise ToolError("Indiquez booking_id, ou bien le nom et l'email du destinataire.")
            start = args.debut or now - timedelta(minutes=args.duree_minutes)
            report = pasted_transcripts.create_meeting(
                db,
                text=args.texte,
                hint=hint,
                title=args.titre or None,
                start=start,
                end=start + timedelta(minutes=args.duree_minutes),
                name=args.nom,
                email=str(args.email).lower(),
                locale=args.langue,
                now=now,
            )
    except pasted_transcripts.PasteError as e:
        raise ToolError(e.message)
    return {
        "report_id": report.id,
        "booking_id": report.booking_id,
        "message": "Transcription reçue. Interlocuteurs puis compte rendu en cours (quelques minutes) ; le brouillon "
        "Gmail sera à relire avant l'envoi. Suivi : etat_compte_rendu.",
    }


def report_status(db: Session, args: StatusArgs, now: datetime) -> dict:
    report = db.get(SessionReport, args.report_id)
    if report is None:
        raise ToolError("Compte rendu introuvable.")
    return {
        "report_id": report.id,
        "statut": STATUS_LABELS[report.status],
        "erreur": report.error,
        "interlocuteurs": report.speakers,
        "synthese": report.summary,
    }


HANDLERS = {
    "rendez_vous_termines": (ListArgs, list_finished),
    "soumettre_transcription": (SubmitArgs, submit),
    "etat_compte_rendu": (StatusArgs, report_status),
}


def call_tool(db: Session, params: dict, now: datetime) -> dict:
    name = params.get("name")
    if name not in HANDLERS:
        raise RpcError(-32602, f"Outil inconnu : {name}")
    model, handler = HANDLERS[name]
    try:
        result = handler(db, model.model_validate(params.get("arguments") or {}), now)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        return _tool_error(f"Argument invalide{' (' + where + ')' if where else ''} : {first['msg']}")
    except ToolError as e:
        return _tool_error(str(e))
    log.info("mcp tool %s called", name)
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "structuredContent": result}


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


# --- JSON-RPC ----------------------------------------------------------------------------------------------------


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def initialize(params: dict) -> dict:
    asked = params.get("protocolVersion")
    return {
        "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
        "instructions": INSTRUCTIONS,
    }


def dispatch(db: Session, message: Any, now: datetime) -> dict | None:
    """The response to one JSON-RPC message, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Requête JSON-RPC invalide"}}
    if "id" not in message:
        return None
    method, params = message["method"], message.get("params") or {}
    try:
        if method == "initialize":
            result = initialize(params)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = call_tool(db, params, now)
        else:
            raise RpcError(-32601, f"Méthode inconnue : {method}")
    except RpcError as e:
        return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": e.code, "message": e.message}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


async def _handle(request: Request, db: Session, now: datetime) -> Response:
    try:
        message = json.loads(await request.body())
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON illisible"}}, 400)
    # Database work off the event loop, like the sync routes.
    response = await run_in_threadpool(dispatch, db, message, now)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response, headers={"Cache-Control": "no-store"})


@router.post("/{token}")
async def mcp_with_url_token(token: str, request: Request, db: Session = Depends(get_db), now=Depends(get_now)):
    check_token(request, token)
    return await _handle(request, db, now)


@router.post("")
async def mcp_with_bearer(request: Request, db: Session = Depends(get_db), now=Depends(get_now)):
    check_token(request, None)
    return await _handle(request, db, now)


@router.get("/{token}")
@router.get("")
def no_stream():
    """No server-initiated messages: the spec's answer for a server without an SSE stream."""
    return Response(status_code=405, headers={"Allow": "POST"})
