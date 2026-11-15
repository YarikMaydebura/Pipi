"""WebSocket server for the bodies: the desktop pet and the fake robot, connected at the same time.

A body connects to ``ws://<server.host>:<server.port>`` and must send ``hello`` within
``bodies.hello_timeout_s``. ``hello.body`` says which body it is; the server keeps ONE body
object per name (created at startup, see ``create_bodies``) and hands the connection to it.
A new connection for a name replaces the old one for that name only. After ``hello`` every
frame is validated (``parse_body_message``) and given to that body's object, which matches
acks to commands. ``BodyServer.bodies`` is the read-only ``name -> Body`` mapping the session
logic (``BodyManager``) works with; a body object exists even while nothing is connected.

Safety:
- Origin check: a random web page in the participant's browser must not be able to pretend to
  be Pipi's body (cross-site WebSocket hijacking). Allowed: non-browser clients (no Origin),
  Electron's ``file://`` / ``null``, ``http://localhost|127.0.0.1`` pages (dev servers), and a
  page served by THIS machine over the LAN (``http://<private IP or *.local>:<any port>`` whose
  host equals the host the WebSocket was opened on) — that is the fake robot page served by the
  brain's web server and opened on a second laptop. See ``origin_allowed``.
- Invalid frames are logged and ignored; a misbehaving body never crashes the brain.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import Callable, Mapping
from http import HTTPStatus
from types import MappingProxyType
from typing import Any, Protocol

from pydantic import ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from pipi_brain.bodies.base import Body, BodyLog
from pipi_brain.bodies.channel import BodyLink
from pipi_brain.bodies.desktop_pet import DesktopPetBody
from pipi_brain.bodies.fake_robot import FakeRobotBody
from pipi_brain.config import AppConfig
from pipi_brain.protocol import BodyName, BodyToBrain, Hello, parse_body_message
from pipi_brain.resilience import describe_error

MAX_MESSAGE_BYTES = 1 << 20  # bodies only send small JSON messages
CLOSE_POLICY = 1008  # WebSocket close code "policy violation"

_LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")
_HTTP_ORIGIN = re.compile(r"^http://(?P<host>[A-Za-z0-9.\-]+)(:\d+)?$")
_ELECTRON_ORIGINS = frozenset({"file://", "null"})


class BodyServerError(Exception):
    """The server could not start (e.g. the port is already in use)."""


class RemoteBody(Protocol):
    """What the server needs from a body object (DesktopPetBody, FakeRobotBody)."""

    name: str

    def attach(self, link: BodyLink, hello: Hello) -> BodyLink | None: ...

    def detach(self, link: BodyLink, reason: str) -> None: ...

    def receive(self, message: BodyToBrain) -> None: ...


class ServedBody(Body, RemoteBody, Protocol):
    """A Body the session can use that the server can also (dis)connect."""


BodyLogFactory = Callable[[str], BodyLog]  # body name -> where that body logs


def create_bodies(app: AppConfig, log_for: BodyLogFactory) -> dict[BodyName, ServedBody]:
    """One body object per WebSocket body name, created once at startup.

    ``log_for(name)`` gives each body its log function, e.g.
    ``functools.partial(logger.log, body=name)``. The robot side is pet-only config.
    """
    return {
        "desktop_pet": DesktopPetBody(
            app.bodies, robot_side=app.pet.robot_side, log=log_for("desktop_pet")
        ),
        "fake_robot": FakeRobotBody(app.bodies, log=log_for("fake_robot")),
    }


def _host_only(host_header: str | None) -> str | None:
    """``"192.168.1.5:8765"`` -> ``"192.168.1.5"`` (IPv4 / names; IPv6 is not supported)."""
    if not host_header:
        return None
    return host_header.rsplit(":", 1)[0].lower() if ":" in host_header else host_header.lower()


def _is_lan_host(host: str) -> bool:
    """A private / loopback IPv4 literal or an mDNS ``*.local`` name (cannot be registered)."""
    if host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.version == 4 and (address.is_private or address.is_loopback)


def origin_allowed(origin: str | None, host_header: str | None) -> bool:
    """May a client with this ``Origin`` header connect (see the module docstring)?

    The LAN rule needs the page's host to be the host the client connected to, written as an
    IP / ``.local`` name: a DNS-rebinding page has a domain origin and is still rejected.
    """
    if origin is None or origin in _ELECTRON_ORIGINS or _LOCAL_ORIGIN.match(origin):
        return True
    match = _HTTP_ORIGIN.match(origin)
    if match is None:
        return False
    page_host = match.group("host").lower()
    return _is_lan_host(page_host) and page_host == _host_only(host_header)


def _check_origin(connection: ServerConnection, request: Request) -> Response | None:
    """``process_request`` hook: answer 403 to browser pages from other sites."""
    origin = request.headers.get("Origin")
    if origin_allowed(origin, request.headers.get("Host")):
        return None
    return connection.respond(HTTPStatus.FORBIDDEN, "Origin not allowed.\n")


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
        bodies: Mapping[BodyName, ServedBody],
        hello_timeout_s: float,
        log: BodyLog,
    ) -> None:
        self._host = host
        self._port = port
        self._bodies: dict[str, ServedBody] = dict(bodies)
        self._bodies_view: Mapping[str, Body] = MappingProxyType(self._bodies)
        self._hello_timeout_s = hello_timeout_s
        self._log = log
        self._server: Server | None = None

    @classmethod
    def from_config(cls, app: AppConfig, *, log: BodyLog, log_for: BodyLogFactory) -> BodyServer:
        """The session server: every WebSocket body (pet + fake robot) on ``app.server``."""
        return cls(
            host=app.server.host,
            port=app.server.port,
            bodies=create_bodies(app, log_for),
            hello_timeout_s=app.bodies.hello_timeout_s,
            log=log,
        )

    @property
    def bodies(self) -> Mapping[str, Body]:
        """Read-only ``name -> Body`` (e.g. ``"desktop_pet"``, ``"fake_robot"``), fixed at start."""
        return self._bodies_view

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
                process_request=_check_origin,
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
