"""LiveCodex against a scripted app-server speaking JSON-RPC over a real WebSocket — no database."""

import json
import threading
import time

import pytest
from websockets.sync.server import serve

from app.config import get_config
from app.services import codex
from app.services.codex import (
    CodexAccount,
    CodexNotConnected,
    CodexTurnFailed,
    CodexUnavailable,
    LiveCodex,
    Rpc,
    login_outcome,
)

TOKEN = "capability-token-123"
CHATGPT = {"account": {"type": "chatgpt", "email": "suan@iafluence.fr", "planType": "plus"}, "requiresOpenaiAuth": True}
NO_ACCOUNT = {"account": None, "requiresOpenaiAuth": True}


class AppServer:
    """Answers each request with `handlers[method](params, send)`; records everything the client sent."""

    def __init__(self):
        self.received: list[dict] = []
        self.headers: list[str | None] = []
        self.handlers = {
            "initialize": lambda p, send: {"userAgent": "codex-test"},
            "account/read": lambda p, send: CHATGPT,
        }
        self._server = serve(self._handle, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self._server.socket.getsockname()[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def _handle(self, ws):
        self.headers.append(ws.request.headers.get("Authorization"))
        if ws.request.headers.get("Authorization") != f"Bearer {TOKEN}":
            ws.close(1008, "unauthorized")
            return

        def send(message):
            ws.send(json.dumps(message))

        for raw in ws:
            message = json.loads(raw)
            self.received.append(message)
            if "method" not in message or "id" not in message:
                continue  # notification or our own reply to a server request
            handler = self.handlers.get(message["method"])
            if handler is None:
                send({"id": message["id"], "error": {"code": -32601, "message": f"unknown {message['method']}"}})
                continue
            result = handler(message.get("params"), send)
            if result is not NO_REPLY:
                send({"id": message["id"], "result": result})

    def methods(self):
        return [m["method"] for m in self.received if "method" in m]

    def params(self, method):
        return next(m["params"] for m in self.received if m.get("method") == method)

    def close(self):
        self._server.shutdown()


NO_REPLY = object()


@pytest.fixture
def server(monkeypatch):
    s = AppServer()
    monkeypatch.setattr(get_config(), "codex_app_server_url", s.url)
    monkeypatch.setattr(get_config(), "codex_ws_token", TOKEN)
    monkeypatch.setattr(get_config(), "codex_turn_timeout_seconds", 5)
    yield s
    s.close()


def test_account_of_the_chatgpt_plan(server):
    assert LiveCodex().account() == CodexAccount("suan@iafluence.fr", "plus")
    assert server.headers == [f"Bearer {TOKEN}"]
    assert server.methods() == ["initialize", "initialized", "account/read"]
    assert server.params("initialize") == {"clientInfo": codex.CLIENT_INFO, "capabilities": None}
    assert server.params("account/read") == {"refreshToken": False}


@pytest.mark.parametrize("result", [NO_ACCOUNT, {"account": {"type": "apiKey"}}, None])
def test_no_chatgpt_account(server, result):
    server.handlers["account/read"] = lambda p, send: result
    assert LiveCodex().account() is None


def test_wrong_token_or_no_server(server, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_ws_token", "wrong")
    with pytest.raises(CodexUnavailable, match="connexion au codex app-server perdue|injoignable"):
        LiveCodex().account()
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://127.0.0.1:9")
    with pytest.raises(CodexUnavailable, match=r"^codex app-server injoignable \(ConnectionRefusedError\)$"):
        LiveCodex().account()
    monkeypatch.setattr(get_config(), "codex_app_server_url", "")
    with pytest.raises(CodexUnavailable, match="CODEX_APP_SERVER_URL n'est pas configuré"):
        LiveCodex().account()


def test_error_answers_and_silence(server, monkeypatch):
    with pytest.raises(CodexUnavailable, match="^account/logout : unknown account/logout$"):
        LiveCodex().logout()

    server.handlers["account/read"] = lambda p, send: NO_REPLY
    monkeypatch.setattr(codex, "REQUEST_TIMEOUT_S", 0.3)
    with pytest.raises(CodexUnavailable, match="pas de réponse du codex app-server à account/read"):
        LiveCodex().account()


def test_logout_and_cancel(server):
    server.handlers["account/logout"] = lambda p, send: {}
    server.handlers["account/login/cancel"] = lambda p, send: {"status": "canceled"}
    LiveCodex().logout()
    LiveCodex().cancel_login("login-7")
    assert server.params("account/logout") is None
    assert server.params("account/login/cancel") == {"loginId": "login-7"}


# --- device login ------------------------------------------------------------------------------------------------


def device_code(p, send):
    return {
        "type": "chatgptDeviceCode",
        "loginId": "login-1",
        "verificationUrl": "https://auth.openai.com/codex/device",
        "userCode": "ABCD-1234",
    }


def wait_for(done, timeout=5):
    assert done.wait(timeout), "on_done was never called"


@pytest.mark.parametrize(
    "notification, expected",
    [
        ({"loginId": "login-1", "success": True, "error": None}, ("login-1", "COMPLETED", None)),
        ({"loginId": "login-1", "success": False, "error": "device code expired"}, ("login-1", "EXPIRED", "device code expired")),
        ({"loginId": None, "success": False, "error": "access_denied"}, ("login-1", "DENIED", "access_denied")),
    ],
    ids=["completed", "expired", "denied"],
)
def test_device_login_outcome_arrives_on_the_same_connection(server, notification, expected):
    started = threading.Event()

    def start(p, send):
        # The admin approves a little later: the notification follows the answer.
        def later():
            started.wait(5)
            time.sleep(0.05)
            send({"method": "account/updated", "params": {"authMode": "chatgpt", "planType": "plus"}})
            send({"method": "account/login/completed", "params": {"loginId": "other", "success": True, "error": None}})
            send({"method": "account/login/completed", "params": notification | {"onboardingEntrypoint": None}})

        threading.Thread(target=later, daemon=True).start()
        return device_code(p, send)

    server.handlers["account/login/start"] = start
    outcomes, done = [], threading.Event()
    code = LiveCodex().start_login(lambda *a: (outcomes.append(a), done.set()))
    started.set()
    assert (code.login_id, code.verification_url, code.user_code) == (
        "login-1",
        "https://auth.openai.com/codex/device",
        "ABCD-1234",
    )
    assert server.params("account/login/start") == {"type": "chatgptDeviceCode"}
    wait_for(done)
    assert outcomes == [expected]


def test_device_login_times_out_as_expired(server, monkeypatch):
    monkeypatch.setattr(codex, "DEVICE_CODE_TTL_S", -29.8)
    server.handlers["account/login/start"] = device_code
    outcomes, done = [], threading.Event()
    LiveCodex().start_login(lambda *a: (outcomes.append(a), done.set()))
    wait_for(done)
    assert outcomes == [("login-1", "EXPIRED", None)]


def test_lost_connection_leaves_the_login_pending(server, caplog):
    def start(p, send):
        threading.Timer(0.1, server.close).start()
        return device_code(p, send)

    server.handlers["account/login/start"] = start
    outcomes = []
    LiveCodex().start_login(lambda *a: outcomes.append(a))
    deadline = time.monotonic() + 3
    while "lost the codex app-server connection" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.05)
    assert outcomes == [] and "lost the codex app-server connection" in caplog.text


def test_watcher_errors_are_logged(server, caplog):
    def start(p, send):
        threading.Timer(0.05, lambda: send({"method": "account/login/completed", "params": {"loginId": "login-1"}})).start()
        return device_code(p, send)

    server.handlers["account/login/start"] = start

    def boom(*a):
        raise RuntimeError("db down")

    LiveCodex().start_login(boom)
    deadline = time.monotonic() + 3
    while "codex device login watcher failed" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "codex device login watcher failed" in caplog.text


def test_start_login_error_closes_the_connection(server):
    with pytest.raises(CodexUnavailable, match="unknown account/login/start"):
        LiveCodex().start_login(lambda *a: None)


@pytest.mark.parametrize(
    "success, error, status",
    [
        (True, None, "COMPLETED"),
        (False, "Device code expired", "EXPIRED"),
        (False, "authorization_pending timed out: expired_token", "EXPIRED"),
        (False, "access_denied", "DENIED"),
        (False, "user declined", "DENIED"),
        (False, "Connexion refusée", "DENIED"),
        (False, "login cancelled", "CANCELLED"),
        (False, "network error", "ERROR"),
        (False, None, "ERROR"),
    ],
)
def test_login_outcome(success, error, status):
    assert login_outcome(success, error) == status


# --- summary turn ------------------------------------------------------------------------------------------------


def scripted_turn(server, *, status="completed", error=None, messages=("brouillon", '{"ok": true}'), extra=()):
    server.handlers["thread/start"] = lambda p, send: {"thread": {"id": "thr-1"}, "model": "gpt-5.5"}

    def turn_start(p, send):
        def later():
            time.sleep(0.05)
            for message in extra:
                send(message)
            send({"method": "item/completed", "params": {"threadId": "thr-1", "turnId": "other", "item": {"type": "agentMessage", "text": "x"}}})
            send({"method": "item/completed", "params": {"threadId": "thr-1", "turnId": "turn-1", "item": {"type": "reasoning", "text": "…"}}})
            for text in messages:
                send({"method": "item/completed", "params": {"threadId": "thr-1", "turnId": "turn-1", "item": {"type": "agentMessage", "text": text}}})
            send({"method": "turn/completed", "params": {"threadId": "thr-1", "turn": {"id": "turn-1", "status": status, "error": error}}})

        threading.Thread(target=later, daemon=True).start()
        return {"turn": {"id": "turn-1", "status": "inProgress", "items": []}}

    server.handlers["turn/start"] = turn_start


def test_run_turn_returns_the_last_agent_message(server, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_model", "gpt-5.5")
    approvals = [{"id": 99, "method": "item/commandExecution/requestApproval", "params": {"command": "rm -rf /"}}]
    scripted_turn(server, extra=approvals)
    schema = {"type": "object"}
    assert LiveCodex().run_turn(instructions="Consignes", prompt="Transcription", output_schema=schema) == '{"ok": true}'

    assert server.params("account/read") == {"refreshToken": True}
    assert server.params("thread/start") == {
        "model": "gpt-5.5",
        "approvalPolicy": "never",
        "sandbox": "read-only",
        "ephemeral": True,
        "developerInstructions": "Consignes",
        "serviceName": "iafluence_booking",
    }
    assert server.params("turn/start") == {
        "threadId": "thr-1",
        "input": [{"type": "text", "text": "Transcription", "text_elements": []}],
        "outputSchema": schema,
    }
    # A server request (approval) is refused, never granted.
    [reply] = [m for m in server.received if m.get("id") == 99]
    assert reply == {"id": 99, "error": {"code": -32601, "message": "not supported by this client"}}


def test_default_model_is_left_to_codex(server):
    scripted_turn(server)
    LiveCodex().run_turn(instructions="i", prompt="p", output_schema={})
    assert server.params("thread/start")["model"] is None


def test_run_turn_needs_a_connected_account(server):
    server.handlers["account/read"] = lambda p, send: NO_ACCOUNT
    with pytest.raises(CodexNotConnected):
        LiveCodex().run_turn(instructions="i", prompt="p", output_schema={})
    assert "thread/start" not in server.methods()


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"status": "failed", "error": {"message": "usage limit reached"}}, "tour Codex failed : usage limit reached"),
        ({"status": "interrupted", "error": None}, "tour Codex interrupted : interrupted"),
        ({"messages": ()}, "Codex n'a renvoyé aucun message"),
    ],
)
def test_run_turn_failures(server, kwargs, message):
    scripted_turn(server, **kwargs)
    with pytest.raises(CodexTurnFailed, match=f"^{message}$"):
        LiveCodex().run_turn(instructions="i", prompt="p", output_schema={})


def test_run_turn_timeout_interrupts_the_turn(server, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_turn_timeout_seconds", 0.3)
    server.handlers["thread/start"] = lambda p, send: {"thread": {"id": "thr-1"}}
    server.handlers["turn/start"] = lambda p, send: {"turn": {"id": "turn-1"}}
    server.handlers["turn/interrupt"] = lambda p, send: {}
    with pytest.raises(CodexTurnFailed, match="délai dépassé pour le résumé Codex"):
        LiveCodex().run_turn(instructions="i", prompt="p", output_schema={})
    assert server.params("turn/interrupt") == {"threadId": "thr-1", "turnId": "turn-1"}


def test_run_turn_timeout_even_if_the_interrupt_fails(server, monkeypatch):
    monkeypatch.setattr(get_config(), "codex_turn_timeout_seconds", 0.3)
    server.handlers["thread/start"] = lambda p, send: {"thread": {"id": "thr-1"}}
    server.handlers["turn/start"] = lambda p, send: {"turn": {"id": "turn-1"}}
    with pytest.raises(CodexTurnFailed, match="délai dépassé"):
        LiveCodex().run_turn(instructions="i", prompt="p", output_schema={})


def test_connection_lost_during_the_turn(server):
    server.handlers["thread/start"] = lambda p, send: {"thread": {"id": "thr-1"}}

    def turn_start(p, send):
        threading.Timer(0.05, server.close).start()
        return {"turn": {"id": "turn-1"}}

    server.handlers["turn/start"] = turn_start
    with pytest.raises(CodexUnavailable, match="connexion au codex app-server perdue"):
        LiveCodex().run_turn(instructions="i", prompt="p", output_schema={})


def test_initialize_failure_closes_the_socket(server, monkeypatch):
    server.handlers["initialize"] = lambda p, send: NO_REPLY
    monkeypatch.setattr(codex, "REQUEST_TIMEOUT_S", 0.3)
    closed = []
    original = Rpc.close
    monkeypatch.setattr(Rpc, "close", lambda self: (closed.append(True), original(self)))
    with pytest.raises(CodexUnavailable, match="pas de réponse du codex app-server à initialize"):
        LiveCodex().account()
    assert closed == [True]
