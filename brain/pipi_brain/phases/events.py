"""One place for everything the session reports: the study log and the WoZ panel.

``SessionEvents.log`` writes ``events.jsonl`` with the current phase and active body;
``push`` sends ``state_update`` / ``turn`` / ``alert`` to every WoZ listener; ``alert``
does both. A broken listener is logged and dropped, it never stops the session.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from pipi_brain.logging_study import StudyLogger
from pipi_brain.protocol import Alert, BrainToWoz
from pipi_brain.resilience import describe_error
from pipi_brain.woz_api import WozListener

AlertLevel = Literal["info", "warning", "error"]


class SessionEvents:
    def __init__(
        self,
        logger: StudyLogger,
        *,
        phase: Callable[[], str | None],
        body: Callable[[], str | None],
    ) -> None:
        self.logger = logger
        self._phase = phase
        self._body = body
        self._listeners: list[WozListener] = []

    def log(
        self, event_type: str, data: Mapping[str, Any] | None = None, *, body: str | None = None
    ) -> None:
        self.logger.log(event_type, data, phase=self._phase(), body=body or self._body())

    def body_log(self, body_name: str) -> Callable[[str, Mapping[str, Any]], None]:
        """Log function for one body's own events (body_message, body_error, ...)."""

        def log(event_type: str, data: Mapping[str, Any]) -> None:
            self.logger.log(event_type, data, phase=self._phase(), body=body_name)

        return log

    def subscribe(self, listener: WozListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def push(self, message: BrainToWoz) -> None:
        for listener in list(self._listeners):
            try:
                listener(message)
            except Exception as exc:  # a broken panel connection must not stop Pipi
                self._listeners.remove(listener)
                self.log("woz_listener_error", {"error": describe_error(exc)})

    def alert(self, level: AlertLevel, message: str) -> None:
        self.log("alert", {"level": level, "message": message})
        self.push(Alert(level=level, message=message))
