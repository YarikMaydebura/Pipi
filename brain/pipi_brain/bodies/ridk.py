"""Keeps the RidK (Robots in de Klas) WAMP session to the real Alpha Mini open for a session.

Set up like the course examples and ``tools/robot_check.py`` (autobahn asyncio, msgpack, the
robot's realm from ``RIDK_REALM``), but long-lived: there is no ``main``, the component keeps
reconnecting (``max_retries: -1``) and hands each joined session to the body with
``attach`` / ``detach``. ``start`` returns at once: the session never waits for the robot here
(a migration waits ``robot_connect_wait_s`` and falls back to the pet). The realm is a secret:
it is never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any, Protocol

from pipi_brain.bodies.base import BodyLog
from pipi_brain.resilience import describe_error


class RidkBody(Protocol):
    def attach(self, session: Any) -> None: ...

    def detach(self, reason: str) -> None: ...

    async def close(self) -> None: ...


class Component(Protocol):
    """The part of ``autobahn.asyncio.component.Component`` used here."""

    def on_join(self, fn: Callable[..., Any]) -> Any: ...

    def on_leave(self, fn: Callable[..., Any]) -> Any: ...

    def start(self, loop: asyncio.AbstractEventLoop) -> Any: ...

    def stop(self) -> Any: ...


ComponentFactory = Callable[[str, str], Component]


def autobahn_component(url: str, realm: str) -> Component:
    """The real, reconnecting connection (only imported when a robot is used)."""
    from autobahn.asyncio.component import Component as AutobahnComponent

    transport = {"url": url, "serializers": ["msgpack"], "max_retries": -1}
    component: Component = AutobahnComponent(transports=[transport], realm=realm)
    return component


class RidkConnector:
    def __init__(
        self,
        url: str,
        realm: str,
        body: RidkBody,
        *,
        log: BodyLog,
        factory: ComponentFactory | None = None,
    ) -> None:
        self._url = url
        self._realm = realm
        self._body = body
        self._log = log
        self._factory = factory if factory is not None else autobahn_component
        self._component: Component | None = None
        self._running: asyncio.Future[Any] | None = None

    async def start(self) -> None:
        """Start connecting in the background. Never raises: problems are logged."""
        if self._component is not None:
            return
        try:
            component = self._factory(self._url, self._realm)
            component.on_join(self._joined)
            component.on_leave(self._left)
            self._running = asyncio.ensure_future(component.start(asyncio.get_running_loop()))
        except Exception as exc:  # e.g. autobahn missing: the session goes on without the robot
            self._log("body_error", {"body": "alpha_mini", "error": self._safe(exc)})
            return
        self._component = component
        self._running.add_done_callback(self._ended)
        self._log("ridk_connecting", {"url": self._url})  # never the realm

    async def stop(self) -> None:
        component, self._component = self._component, None
        running, self._running = self._running, None
        await self._body.close()
        self._body.detach("session ended")
        if component is not None:
            with contextlib.suppress(Exception):
                stopped = component.stop()
                if asyncio.isfuture(stopped) or asyncio.iscoroutine(stopped):
                    await asyncio.wait({asyncio.ensure_future(stopped)}, timeout=2)
        if running is not None and not running.done():
            running.cancel()
            with contextlib.suppress(BaseException):
                await running

    # --- autobahn callbacks --------------------------------------------------------------------

    def _joined(self, session: Any, _details: Any = None) -> None:
        self._body.attach(session)

    def _left(self, _session: Any, details: Any = None) -> None:
        reason = str(getattr(details, "reason", None) or "left the realm")
        self._body.detach(f"ridk: {reason.replace(self._realm, '<realm>')}")

    def _ended(self, future: asyncio.Future[Any]) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        self._body.detach("ridk connection ended")
        if exc is not None:
            self._log("body_error", {"body": "alpha_mini", "error": self._safe(exc)})

    def _safe(self, exc: BaseException) -> str:
        """The error text without the realm (an error like no_such_realm may quote it)."""
        return (
            describe_error(exc).replace(self._realm, "<realm>")
            if self._realm
            else describe_error(exc)
        )
