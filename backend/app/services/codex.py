"""Client of `codex app-server` (deploy/codex): device login with the ChatGPT plan, and one agent turn per summary.

JSON-RPC over a WebSocket on the internal Docker network, authenticated with a shared capability token
(CODEX_WS_TOKEN). The OAuth tokens of the ChatGPT account never leave the codex container: this module only
sees the account email and plan, and the device code the admin types on the OpenAI page.
Prompts carry the transcript: nothing here logs them, and threads are ephemeral (not saved by Codex).
"""

import itertools
import json
import logging
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, Protocol

from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from app.config import get_config

log = logging.getLogger(__name__)

CLIENT_INFO = {"name": "iafluence_booking", "title": "IAfluence Booking", "version": "1.0"}
REQUEST_TIMEOUT_S = 30
# OpenAI device codes are valid 15 minutes.
DEVICE_CODE_TTL_S = 15 * 60
ERROR_MAX_LEN = 300


class CodexUnavailable(Exception):
    """app-server unreachable, token refused or protocol error."""


class CodexNotConnected(Exception):
    """No ChatGPT account connected (never connected, logged out, or the session expired)."""


class CodexTurnFailed(Exception):
    """The agent turn failed, was interrupted or took too long."""


@dataclass(frozen=True)
class CodexAccount:
    email: str | None
    plan: str | None


@dataclass(frozen=True)
class DeviceCode:
    login_id: str
    verification_url: str
    user_code: str


# on_done(login_id, status, error): status is COMPLETED, EXPIRED, DENIED, CANCELLED or ERROR.
LoginDone = Callable[[str, str, str | None], None]


class CodexGateway(Protocol):
    def account(self) -> CodexAccount | None: ...

    def start_login(self, on_done: LoginDone) -> DeviceCode:
        """Start the device authorization; `on_done` is called from another thread when it ends."""

    def cancel_login(self, login_id: str) -> None: ...

    def logout(self) -> None: ...

    def run_turn(self, *, instructions: str, prompt: str, output_schema: dict) -> str:
        """Final agent message of one turn, constrained by `output_schema`."""


def short(message: Any) -> str:
    return str(message)[:ERROR_MAX_LEN]


def login_outcome(success: bool, error: str | None) -> str:
    """Status of a finished device login, from the app-server notification."""
    if success:
        return "COMPLETED"
    text = (error or "").lower()
    if "expire" in text:
        return "EXPIRED"
    if "denied" in text or "declined" in text or "refus" in text:
        return "DENIED"
    if "cancel" in text:
        return "CANCELLED"
    return "ERROR"


class Rpc:
    """One initialized app-server connection. Server notifications are queued until someone waits for them."""

    def __init__(self, ws: ClientConnection, stack: ExitStack | None = None):
        self._ws = ws
        self._stack = stack
        self._ids = itertools.count(1)
        self.notifications: list[dict] = []

    @classmethod
    def open(cls) -> "Rpc":
        cfg = get_config()
        if not cfg.codex_app_server_url:
            raise CodexUnavailable("CODEX_APP_SERVER_URL n'est pas configuré")
        stack = ExitStack()
        try:
            ws = stack.enter_context(
                connect(
                    cfg.codex_app_server_url,
                    additional_headers={"Authorization": f"Bearer {cfg.codex_ws_token}"},
                    open_timeout=10,
                    max_size=16 * 1024 * 1024,
                )
            )
        except (OSError, WebSocketException) as e:
            raise CodexUnavailable(f"codex app-server injoignable ({type(e).__name__})") from e
        rpc = cls(ws, stack)
        try:
            rpc.request("initialize", {"clientInfo": CLIENT_INFO, "capabilities": None})
            rpc.send({"method": "initialized"})
        except BaseException:
            rpc.close()
            raise
        return rpc

    def close(self) -> None:
        self._ws.close()
        if self._stack is not None:
            self._stack.close()

    def __enter__(self) -> "Rpc":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send(self, message: dict) -> None:
        try:
            self._ws.send(json.dumps(message))
        except (OSError, WebSocketException) as e:
            raise CodexUnavailable(f"connexion au codex app-server perdue ({type(e).__name__})") from e

    def _receive(self, deadline: float) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        try:
            message = json.loads(self._ws.recv(timeout=remaining))
        except TimeoutError:
            raise
        except (OSError, WebSocketException, ValueError) as e:
            raise CodexUnavailable(f"connexion au codex app-server perdue ({type(e).__name__})") from e
        if "method" in message and "id" in message:
            # A server request (approval, user input…): never granted to an unattended summary.
            self.send({"id": message["id"], "error": {"code": -32601, "message": "not supported by this client"}})
            return {}
        return message

    def request(self, method: str, params: Any, timeout: float | None = None) -> Any:
        request_id = next(self._ids)
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + (timeout or REQUEST_TIMEOUT_S)
        while True:
            try:
                message = self._receive(deadline)
            except TimeoutError:
                raise CodexUnavailable(f"pas de réponse du codex app-server à {method}") from None
            if message.get("id") == request_id:
                if "error" in message:
                    raise CodexUnavailable(f"{method} : {short(message['error'].get('message'))}")
                return message.get("result")
            if "method" in message:
                self.notifications.append(message)

    def next_notification(self, deadline: float) -> dict:
        """Next queued or incoming notification; TimeoutError at the deadline."""
        while True:
            if self.notifications:
                return self.notifications.pop(0)
            message = self._receive(deadline)
            if "method" in message:
                return message


def account_from(result: dict) -> CodexAccount | None:
    account = (result or {}).get("account")
    if not account or account.get("type") != "chatgpt":
        return None
    return CodexAccount(email=account.get("email"), plan=account.get("planType"))


class LiveCodex:
    def __init__(self, open_rpc: Callable[[], Rpc] = Rpc.open):
        self._open = open_rpc

    def account(self) -> CodexAccount | None:
        with self._open() as rpc:
            return account_from(rpc.request("account/read", {"refreshToken": False}))

    def start_login(self, on_done: LoginDone) -> DeviceCode:
        rpc = self._open()
        try:
            result = rpc.request("account/login/start", {"type": "chatgptDeviceCode"})
            code = DeviceCode(result["loginId"], result["verificationUrl"], result["userCode"])
        except BaseException:
            rpc.close()
            raise
        # The connection that started the login stays open to receive its outcome.
        threading.Thread(target=self._watch_login, args=(rpc, code.login_id, on_done), daemon=True).start()
        return code

    @staticmethod
    def _watch_login(rpc: Rpc, login_id: str, on_done: LoginDone) -> None:
        deadline = time.monotonic() + DEVICE_CODE_TTL_S + 30
        try:
            while True:
                message = rpc.next_notification(deadline)
                params = message.get("params") or {}
                if message["method"] == "account/login/completed" and params.get("loginId") in (login_id, None):
                    error = params.get("error")
                    on_done(login_id, login_outcome(bool(params.get("success")), error), short(error) if error else None)
                    return
        except TimeoutError:
            on_done(login_id, "EXPIRED", None)
        except CodexUnavailable:
            # Left PENDING: the status check of the admin page asks the app-server directly.
            log.warning("lost the codex app-server connection while waiting for the device login")
        except Exception:
            log.exception("codex device login watcher failed")
        finally:
            rpc.close()

    def cancel_login(self, login_id: str) -> None:
        with self._open() as rpc:
            rpc.request("account/login/cancel", {"loginId": login_id})

    def logout(self) -> None:
        with self._open() as rpc:
            rpc.request("account/logout", None)

    def run_turn(self, *, instructions: str, prompt: str, output_schema: dict) -> str:
        cfg = get_config()
        with self._open() as rpc:
            if account_from(rpc.request("account/read", {"refreshToken": True})) is None:
                raise CodexNotConnected("Codex n'est pas connecté")
            thread = rpc.request(
                "thread/start",
                {
                    "model": cfg.codex_model or None,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "developerInstructions": instructions,
                    "serviceName": "iafluence_booking",
                },
            )["thread"]
            turn = rpc.request(
                "turn/start",
                {
                    "threadId": thread["id"],
                    "input": [{"type": "text", "text": prompt, "text_elements": []}],
                    "outputSchema": output_schema,
                },
            )["turn"]
            deadline = time.monotonic() + cfg.codex_turn_timeout_seconds
            answer = None
            try:
                while True:
                    message = rpc.next_notification(deadline)
                    params = message.get("params") or {}
                    if message["method"] == "item/completed" and params.get("turnId") == turn["id"]:
                        item = params.get("item") or {}
                        if item.get("type") == "agentMessage":
                            answer = item.get("text")
                    elif message["method"] == "turn/completed" and params.get("turn", {}).get("id") == turn["id"]:
                        done = params["turn"]
                        if done.get("status") != "completed":
                            error = (done.get("error") or {}).get("message") or done.get("status")
                            raise CodexTurnFailed(f"tour Codex {done.get('status')} : {short(error)}")
                        break
            except TimeoutError:
                try:
                    rpc.request("turn/interrupt", {"threadId": thread["id"], "turnId": turn["id"]}, timeout=5)
                except CodexUnavailable:
                    pass
                raise CodexTurnFailed("délai dépassé pour le résumé Codex") from None
        if not answer:
            raise CodexTurnFailed("Codex n'a renvoyé aucun message")
        return answer
