"""The contract between the session logic and the WoZ server (M3).

The WoZ server (``woz_server.py``) only talks to a ``WozBackend``; the session controller
(``phases/``) implements it. Neither side imports the other, so they can be built and tested
separately (each with a fake of the other).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .protocol import BrainToWoz, StateUpdate, WozCommand

WozListener = Callable[[BrainToWoz], None]


@dataclass(frozen=True)
class CommandOutcome:
    """Result of one WoZ command; sent back to the panel as an ``ack``."""

    ok: bool
    error: str | None = None


class WozBackend(Protocol):
    """What the WoZ panel can see and do. Implemented by the session controller."""

    def snapshot(self) -> StateUpdate:
        """The current state; sent to a panel as its first message after connecting."""
        ...

    async def handle_woz(self, command: WozCommand) -> CommandOutcome:
        """Validate and apply one command (logged with its reason). Never raises."""
        ...

    def subscribe(self, listener: WozListener) -> Callable[[], None]:
        """Push every ``state_update`` / ``turn`` / ``alert`` to ``listener``.

        Returns a function that unsubscribes. Listeners must be fast and must not raise.
        """
        ...
