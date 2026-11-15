"""WebSocket server for the bodies (desktop pet now, fake robot in M3).

A body connects to ``ws://<server.host>:<server.port>`` and must send ``hello`` within
``bodies.hello_timeout_s``. After that every frame is validated (``parse_body_message``) and
handed to that body's object (e.g. ``DesktopPetBody``), which matches acks to commands.

Safety:
- Only browser pages from this machine (http://localhost / 127.0.0.1, Electron's file://) or
  non-browser clients may connect: the Origin check stops a random web page in the
  participant's browser from pretending to be Pipi's body (cross-site WebSocket hijacking).
- Invalid frames are logged and ignored; a misbehaving body never crashes the brain.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin

from pipi_brain.bodies.base import BodyLog
from pipi_brain.bodies.channel import BodyLink
from pipi_brain.protocol import BodyName, BodyToBrain, Hello, parse_body_message
from pipi_brain.resilience import describe_error

MAX_MESSAGE_BYTES = 1 << 20  # bodies only send small JSON messages
ALLOWED_ORIGINS: list[Origin | re.Pattern[str] | None] = [
    None,  # no Origin header: Python clients, tests
    Origin("file://"),  # the packaged Electron pet
    Origin("null"),
    re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"),  # dev servers on this machine
]
CLOSE_POLICY = 1008  # WebSocket close code "policy violation"


class BodyServerError(Exception):
    """The server could not start (e.g. the port is already in use)."""


class RemoteBody(Protocol):
    """What the server needs from a body object (DesktopPetBody, later FakeRobotBody)."""

    name: str

    def attach(self, link: BodyLink, hello: Hello) -> BodyLink | None: ...

    def detach(self, link: BodyLink, reason: str) -> None: ...

    def receive(self, message: BodyToBrain) -> None: ...


class WebSocketLink:
    """``BodyLink`` over one websockets connection."""

    def __init__(self, connection: ServerConnection) -> None:
        self._connection = connection
        address: Any = connection.remote_address
        self.description = (
            f"{address[0]}:{address[1]}" if isinstance(address, tuple) else str(address)
        )

    async def send(self, text: str) -> None:
        await self._connection.send(text)

    async def close(self) -> None:
        await self._connection.close()


class BodyServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        bodies: Mapping[BodyName, RemoteBody],
        hello_timeout_s: float,
        log: BodyLog,
    ) -> None:
        self._host = host
        self._port = port
        self._bodies = dict(bodies)
        self._hello_timeout_s = hello_timeout_s
        self._log = log
        self._server: Server | None = None

    @property
    def port(self) -> int:
        """The real port (useful with port 0 in tests)."""
        if self._server is None:
            return self._port
        sockets = list(self._server.sockets)
        return int(sockets[0].getsockname()[1]) if sockets else self._port

    @property
    def url(self) -> str:
        return f"ws://{self._host}:{self.port}"

    async def start(self) -> None:
        try:
            self._server = await serve(
                self._handle,
                self._host,
                self._port,
                origins=ALLOWED_ORIGINS,
                max_size=MAX_MESSAGE_BYTES,
            )
        except OSError as exc:
            raise BodyServerError(
                f"cannot listen on {self._host}:{self._port} ({describe_error(exc)}); "
                "is another brain already running?"
            ) from exc
        self._log("server_start", {"url": self.url, "bodies": sorted(self._bodies)})

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self._log("server_stop", {})

    async def __aenter__(self) -> BodyServer:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # --- one connection --------------------------------------------------------------------

    async def _handle(self, connection: ServerConnection) -> None:
        link = WebSocketLink(connection)
        hello = await self._read_hello(connection, link)
        if hello is None:
            return
        body = self._bodies.get(hello.body)
        if body is None:
            self._log(
                "body_error",
                {"remote": link.description, "error": f"no {hello.body} expected; closing"},
            )
            await connection.close(CLOSE_POLICY, f"{hello.body} is not used in this session")
            return
        previous = body.attach(link, hello)
        if previous is not None:
            await previous.close()
        reason = "closed"
        try:
            async for raw in connection:
                self._dispatch(body, link, raw)
        except ConnectionClosed as exc:
            reason = f"connection lost ({exc.rcvd.code if exc.rcvd else 'no close frame'})"
        finally:
            body.detach(link, reason)

    async def _read_hello(self, connection: ServerConnection, link: WebSocketLink) -> Hello | None:
        try:
            raw = await asyncio.wait_for(connection.recv(), self._hello_timeout_s)
            message = parse_body_message(raw)
        except TimeoutError:
            error = f"no hello within {self._hello_timeout_s:g} s"
        except ConnectionClosed:
            return None
        except ValidationError as exc:
            error = f"invalid first message: {describe_error(exc)}"
        else:
            if isinstance(message, Hello):
                return message
            error = f"first message must be hello, got {message.type}"
        self._log("body_error", {"remote": link.description, "error": error})
        await connection.close(CLOSE_POLICY, "say hello first")
        return None

    def _dispatch(self, body: RemoteBody, link: WebSocketLink, raw: str | bytes) -> None:
        try:
            message = parse_body_message(raw)
        except ValidationError as exc:
            self._log(
                "body_error",
                {"remote": link.description, "error": f"invalid message: {describe_error(exc)}"},
            )
            return
        if isinstance(message, Hello):
            self._log("body_error", {"remote": link.description, "error": "repeated hello"})
            return
        body.receive(message)
