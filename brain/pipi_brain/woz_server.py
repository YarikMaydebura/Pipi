"""HTTP + WebSocket server for the Wizard-of-Oz panel (M3, docs/SYSTEM_DESIGN.md §4.8).

One port (``woz.port``, default 8766) serves two things:
- plain HTTP GET: the built web app from ``web/dist`` (``/woz/`` panel, ``/fake-robot/``),
  so on study/demo day nothing but the brain has to run (see ``woz_static.py``);
- WebSocket ``/ws/woz?token=...``: the live panel channel.

Per panel connection:
1. the first message is ``backend.snapshot()`` (a ``state_update``);
2. every ``state_update`` / ``turn`` / ``alert`` the backend publishes is forwarded;
3. each ``woz_command`` is validated, logged, handed to ``backend.handle_woz`` and answered
   with ``ack {ref_id, ok, error}``. Commands run concurrently, so ``emergency_stop`` is never
   stuck behind a slow command. Invalid frames get an error ack/alert and are logged.

The server depends ONLY on the ``WozBackend`` protocol (``woz_api.py``), never on ``phases/``.

Security (the panel can stop and steer a participant session):
- ``WOZ_TOKEN`` is required whenever it is set, and the server refuses to start on a
  non-loopback host (e.g. ``0.0.0.0`` for the LAN) without one. Compared in constant time.
  The token is never logged, printed or sent to the browser.
- The ``Origin`` header must be this server itself or a dev page on localhost
  (stops cross-site WebSocket hijacking from a random web page).
- At most ``woz.max_panels`` panels at once; frames are size-limited.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import http
import ipaddress
import json
import logging
import socket
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr, ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from pipi_brain.config import LoadedConfig, WozConfig
from pipi_brain.protocol import (
    Ack,
    Alert,
    BrainToWoz,
    WozCommand,
    encode,
    parse_woz_message,
)
from pipi_brain.resilience import describe_error, with_timeout
from pipi_brain.woz_api import CommandOutcome, WozBackend
from pipi_brain.woz_static import StaticSite, text_response

WozLog = Callable[[str, Mapping[str, Any]], None]
"""Where the server writes study events (normally ``StudyLogger.log`` with the phase)."""

WS_PATH = "/ws/woz"
MAX_FRAME_BYTES = 64 * 1024  # a command is a few hundred bytes; say_text stays far below this
QUEUE_LIMIT = 500  # messages waiting for one panel; more = panel too slow -> disconnect it
CLOSE_POLICY = 1008
CLOSE_TRY_AGAIN = 1013
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
MIN_TOKEN_CHARS = 8
PLACEHOLDER_TOKENS = frozenset({"change-me", "changeme"})

# websockets logs the request path (which carries ?token=) at DEBUG level. Pin our own logger
# to INFO so the token can never end up in a log, even if someone enables debug logging.
_WS_LOGGER = logging.getLogger("pipi_brain.woz.websockets")
_WS_LOGGER.setLevel(logging.INFO)


class WozServerError(Exception):
    """The WoZ server cannot start (missing token on the LAN, port in use, ...)."""


def is_loopback_host(host: str) -> bool:
    """True if ``host`` only accepts connections from this machine."""
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def origin_allowed(origin: str | None, host_header: str | None) -> bool:
    """Browsers always send Origin; allow our own pages and dev pages on this machine.

    ``None`` (no Origin header) means a non-browser client such as a test or a script; those
    cannot be tricked by a web page, and the token still applies.
    """
    if origin is None:
        return True
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    if (parts.hostname or "") in LOOPBACK_NAMES:
        return True  # Vite dev server / a page opened on this laptop
    return host_header is not None and parts.netloc.lower() == host_header.strip().lower()


def token_matches(expected: SecretStr | None, given: str | None) -> bool:
    """Constant-time token check. No token configured = open (loopback only, see start())."""
    if expected is None:
        return True
    if given is None:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.get_secret_value().encode("utf-8"))


def weak_token(token: SecretStr) -> bool:
    """The .env.example placeholder or a very short token is not good enough for the LAN."""
    value = token.get_secret_value()
    return len(value) < MIN_TOKEN_CHARS or value.lower() in PLACEHOLDER_TOKENS


def lan_address() -> str | None:
    """Best guess of this laptop's LAN IP (for the URL shown to the experimenter).

    Connecting a UDP socket sends no packet; it only asks the OS which interface it would use.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.254.254.254", 1))
            address = str(probe.getsockname()[0])
    except OSError:
        return None
    return None if address.startswith("127.") else address


def _remote(connection: ServerConnection) -> str:
    address: Any = connection.remote_address
    return f"{address[0]}:{address[1]}" if isinstance(address, tuple) else str(address)


def _frame_id(raw: str) -> str | None:
    """The ``id`` of an invalid frame, if it has one, so the panel can match the error ack."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    value = data.get("id") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


class _Panel:
    """One connected panel: an outgoing queue drained by a single sender task."""

    def __init__(self, connection: ServerConnection, on_overflow: Callable[[_Panel], None]):
        self.connection = connection
        self.remote = _remote(connection)
        self.queue: asyncio.Queue[BrainToWoz] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.overflowed = False
        self._on_overflow = on_overflow

    def push(self, message: BrainToWoz) -> None:
        """Backend listener: must be fast and must never raise."""
        if self.overflowed:
            return
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True
            self._on_overflow(self)

    async def send_loop(self) -> None:
        while True:
            message = await self.queue.get()
            try:
                await self.connection.send(encode(message))
            except ConnectionClosed:
                return


class WozServer:
    """The WoZ panel server. Use as ``async with WozServer(...)`` or via ``serve_woz``."""

    def __init__(
        self,
        backend: WozBackend,
        *,
        settings: WozConfig,
        token: SecretStr | None,
        log: WozLog,
    ) -> None:
        self._backend = backend
        self._settings = settings
        self._token = token
        self._log = log
        self._site = StaticSite(settings.web_dist)
        self._server: Server | None = None
        self._panels: set[_Panel] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    # --- lifecycle -------------------------------------------------------------------------

    @property
    def port(self) -> int:
        """The real port (useful with port 0 in tests)."""
        if self._server is None:
            return self._settings.port
        sockets = list(self._server.sockets)
        return int(sockets[0].getsockname()[1]) if sockets else self._settings.port

    @property
    def panel_count(self) -> int:
        return len(self._panels)

    @property
    def token_required(self) -> bool:
        return self._token is not None

    @property
    def web_app_built(self) -> bool:
        return self._site.available

    def panel_url(self) -> str:
        """The URL to open on the WoZ device. The token is a placeholder, never the value."""
        host = self._settings.host
        if host in ("0.0.0.0", "::", ""):
            host = lan_address() or socket.gethostname()
        elif ":" in host:
            host = f"[{host}]"
        query = "?token=<WOZ_TOKEN>" if self.token_required else ""
        return f"http://{host}:{self.port}/woz/{query}"

    async def start(self) -> None:
        host = self._settings.host
        if self._token is None and not is_loopback_host(host):
            raise WozServerError(
                f"woz.host is {host} (reachable from the network) but WOZ_TOKEN is not set. "
                "Add WOZ_TOKEN=<a long random string> to .env, or use host 127.0.0.1."
            )
        if self._token is not None and not is_loopback_host(host) and weak_token(self._token):
            raise WozServerError(
                f"WOZ_TOKEN is too weak for woz.host {host} (the .env.example placeholder or "
                f"shorter than {MIN_TOKEN_CHARS} characters). Set a longer random string in .env."
            )
        try:
            self._server = await serve(
                self._handle,
                host,
                self._settings.port,
                process_request=self._process_request,
                max_size=MAX_FRAME_BYTES,
                logger=_WS_LOGGER,
            )
        except OSError as exc:
            raise WozServerError(
                f"cannot listen on {host}:{self._settings.port} ({describe_error(exc)}); "
                "is another brain already running?"
            ) from exc
        self._log(
            "woz_server_start",
            {
                "host": host,
                "port": self.port,
                "token_required": self.token_required,
                "max_panels": self._settings.max_panels,
                "web_app_built": self.web_app_built,
            },
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._log("woz_server_stop", {})

    async def __aenter__(self) -> WozServer:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # --- HTTP: static files + WebSocket gatekeeping ----------------------------------------

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        parts = urlsplit(request.path)
        if parts.path != WS_PATH:
            return self._site.respond(parts.path, parts.query)
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return text_response(http.HTTPStatus.BAD_REQUEST, "WebSocket endpoint.\n")
        rejection = self._check_access(request, parts.query)
        if rejection is None:
            return None  # proceed with the WebSocket handshake
        status, reason = rejection
        self._log("woz_rejected", {"remote": _remote(connection), "reason": reason})
        return text_response(status, f"Rejected: {reason}.\n")

    def _check_access(self, request: Request, query: str) -> tuple[http.HTTPStatus, str] | None:
        if not origin_allowed(request.headers.get("Origin"), request.headers.get("Host")):
            return http.HTTPStatus.FORBIDDEN, "origin not allowed"
        given = parse_qs(query).get("token", [None])[0]
        if not token_matches(self._token, given):
            # Same answer for a missing and a wrong token; the value is never logged.
            return http.HTTPStatus.UNAUTHORIZED, "missing or wrong token"
        if len(self._panels) >= self._settings.max_panels:
            return http.HTTPStatus.SERVICE_UNAVAILABLE, "too many panels connected"
        return None

    # --- one panel -------------------------------------------------------------------------

    async def _handle(self, connection: ServerConnection) -> None:
        if len(self._panels) >= self._settings.max_panels:  # raced past the HTTP check
            self._log("woz_rejected", {"remote": _remote(connection), "reason": "too many panels"})
            await connection.close(CLOSE_TRY_AGAIN, "too many panels connected")
            return
        panel = _Panel(connection, self._drop_slow_panel)
        self._panels.add(panel)
        panel.push(self._safe_snapshot())  # first message, before any event
        unsubscribe = self._backend.subscribe(panel.push)
        sender = asyncio.create_task(panel.send_loop())
        self._log("woz_connected", {"remote": panel.remote, "panels": len(self._panels)})
        reason = "closed"
        try:
            async for raw in connection:
                self._on_frame(panel, raw)
        except ConnectionClosed as exc:
            reason = f"connection lost ({exc.rcvd.code if exc.rcvd else 'no close frame'})"
        finally:
            unsubscribe()
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
            self._panels.discard(panel)
            if panel.overflowed:
                reason = "panel too slow (message queue full)"
            self._log(
                "woz_disconnected",
                {"remote": panel.remote, "reason": reason, "panels": len(self._panels)},
            )

    def _safe_snapshot(self) -> BrainToWoz:
        try:
            return self._backend.snapshot()
        except Exception as exc:  # a backend bug must not kill the panel connection
            error = describe_error(exc)
            self._log("woz_error", {"error": f"snapshot failed: {error}"})
            return Alert(level="error", message=f"Brain state unavailable: {error}")

    def _drop_slow_panel(self, panel: _Panel) -> None:
        self._spawn(panel.connection.close(CLOSE_TRY_AGAIN, "too slow; reconnect"))

    def _on_frame(self, panel: _Panel, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            self._reject_frame(panel, None, "binary frames are not supported")
            return
        try:
            command = parse_woz_message(raw)
        except ValidationError as exc:
            self._reject_frame(panel, _frame_id(raw), f"invalid command: {describe_error(exc)}")
            return
        if command.reason == "other" and not (command.note or "").strip():
            self._reject_frame(panel, command.id, "a note is required when the reason is 'other'")
            return
        self._log(
            "woz_command",
            {
                "remote": panel.remote,
                "command_id": command.id,
                "command": command.command,
                "args": dict(command.args),
                "reason": command.reason,
                "note": command.note,
            },
        )
        self._spawn(self._run_command(panel, command))

    def _reject_frame(self, panel: _Panel, ref_id: str | None, error: str) -> None:
        self._log("woz_invalid", {"remote": panel.remote, "ref_id": ref_id, "error": error})
        if ref_id is not None:
            panel.push(Ack(ref_id=ref_id, ok=False, error=error))
        else:
            panel.push(Alert(level="error", message=error))

    # --- commands --------------------------------------------------------------------------

    async def _run_command(self, panel: _Panel, command: WozCommand) -> None:
        start = time.perf_counter()
        call = asyncio.ensure_future(self._call_backend(command))
        timeout = self._settings.command_timeout_s
        try:
            outcome = await with_timeout(asyncio.shield(call), timeout)
        except TimeoutError:
            error = f"no result within {timeout:g} s; the command may still be running"
            panel.push(Ack(ref_id=command.id, ok=False, error=error))
            self._log_ack(command, CommandOutcome(ok=False, error=error), start, timed_out=True)
            outcome = await call  # keep waiting so the final result is logged and shown
            self._log_ack(command, outcome, start, late=True)
            level = "info" if outcome.ok else "error"
            result = "ok" if outcome.ok else f"failed: {outcome.error}"
            panel.push(Alert(level=level, message=f"{command.command} finished late: {result}"))
            return
        panel.push(Ack(ref_id=command.id, ok=outcome.ok, error=outcome.error))
        self._log_ack(command, outcome, start)

    async def _call_backend(self, command: WozCommand) -> CommandOutcome:
        try:
            return await self._backend.handle_woz(command)
        except Exception as exc:  # contract says "never raises"; defend anyway
            return CommandOutcome(ok=False, error=f"brain error: {describe_error(exc)}")

    def _log_ack(
        self,
        command: WozCommand,
        outcome: CommandOutcome,
        start: float,
        *,
        timed_out: bool = False,
        late: bool = False,
    ) -> None:
        data: dict[str, Any] = {
            "command_id": command.id,
            "command": command.command,
            "ok": outcome.ok,
            "error": outcome.error,
            "elapsed_ms": round((time.perf_counter() - start) * 1000),
        }
        if timed_out:
            data["timed_out"] = True
        if late:
            data["late"] = True
        self._log("woz_ack", data)

    def _spawn(self, coroutine: Any) -> None:
        task: asyncio.Task[None] = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


@asynccontextmanager
async def serve_woz(
    backend: WozBackend,
    loaded: LoadedConfig,
    log: WozLog,
    *,
    announce: Callable[[str], None] = print,
) -> AsyncIterator[WozServer]:
    """Run the WoZ server for the duration of an ``async with`` block.

    ``backend`` is the session controller (anything implementing ``WozBackend``); settings
    come from ``loaded.app.woz`` and the token from ``loaded.secrets.woz_token``. ``announce``
    receives one human-readable line with the panel URL (token shown as a placeholder).
    Raises ``WozServerError`` if the server cannot start.

    A session can take it as a factory, e.g.
    ``functools.partial(serve_woz, loaded=loaded, log=woz_log)`` -> ``factory(backend)``.
    """
    server = WozServer(backend, settings=loaded.app.woz, token=loaded.secrets.woz_token, log=log)
    async with server:
        announce(f"WoZ panel: {server.panel_url()}")
        if not server.web_app_built:
            announce(
                "Warning: web/dist is missing, so the panel page cannot load. "
                "Run `npm run build` in the repo root."
            )
        yield server
