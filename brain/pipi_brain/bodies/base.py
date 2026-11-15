"""The Body interface: everything that can render Pipi implements it (docs/SYSTEM_DESIGN.md 4.2).

The brain never knows *which* body it talks through. Every method returns a result object
instead of raising: a body that is not connected or does not answer in time is a normal,
logged situation, never a crash. The caller decides on the fallback (e.g. play the audio on
the laptop speaker instead).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pipi_brain.protocol import Expression, EyeState
from pipi_brain.speech.base import SpeechAudio

Entrance = Literal["jump_in", "wake_up", "fade_in"]
Exit = Literal["jump_out", "sleep", "fade_out"]

NOT_CONNECTED = "not connected"


@dataclass(frozen=True)
class BodyResult:
    """Outcome of one command (eyes, motion, caption, activate, ...)."""

    ok: bool
    error: str | None = None
    elapsed_ms: int = 0
    timed_out: bool = False


@dataclass(frozen=True)
class SpeakResult:
    """Outcome of ``speak``.

    ``delivered`` = the body accepted the message (it shows the caption and plays the audio).
    ``finished`` = the body reported ``speech_done`` in time. Delivered but not finished means
    the body is probably still talking or lost the connection mid-way; do NOT replay the audio.
    """

    delivered: bool
    finished: bool
    duration_ms: int | None = None  # as reported by the body
    error: str | None = None
    elapsed_ms: int = 0


class BodyLog(Protocol):
    """Where a body writes its events (normally ``StudyLogger.log`` with phase and body)."""

    def __call__(self, event_type: str, data: Mapping[str, Any]) -> None: ...


class Body(Protocol):
    name: str

    @property
    def connected(self) -> bool: ...

    async def wait_connected(self, timeout_s: float) -> bool:
        """True as soon as the body is connected; False after ``timeout_s``."""
        ...

    async def activate(self, entrance: Entrance) -> BodyResult:
        """Play the entrance animation; returns when it has finished."""
        ...

    async def deactivate(self, exit: Exit) -> BodyResult:
        """Play the exit animation; returns when it has finished."""
        ...

    async def speak(
        self, text: str, audio: SpeechAudio | None, expression: Expression = "idle"
    ) -> SpeakResult:
        """Show/say ``text`` (audio None = captions only); returns when speech is done."""
        ...

    async def set_eyes(self, state: EyeState) -> BodyResult: ...

    async def play_motion(self, name: str) -> BodyResult: ...

    async def show_caption(self, text: str | None) -> BodyResult: ...

    def health(self) -> str:
        """Short status for health checks and the terminal, e.g. 'connected (0.1.0)'."""
        ...
