"""The blink detector contract for the staring contest (docs/GAMES.md §3.3).

The staring game (``games/staring.py``) only knows this interface; the real detector
(``vision/blink.py``: webcam + MediaPipe) and the test fake (``fakes.FakeBlinkDetector``)
implement it. Privacy (CLAUDE.md): camera frames stay in memory and are never stored or sent
anywhere.

Usage per round: ``check()`` decides between mode ``detect`` (ok) and ``pretend`` (the reason
is logged), then ``wait_for_blink()`` is armed while the participant stares; cancelling the
call disarms it. ``close()`` releases the camera at the end of the game.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BlinkDetectorError(Exception):
    """The detector cannot work (camera gone, model failed): the game switches to pretend."""


@dataclass(frozen=True)
class VisionCheck:
    """Can the detector be trusted right now? ``ok`` False -> pretend mode with ``reason``."""

    ok: bool
    fps: float = 0.0
    reason: str | None = None  # e.g. "no camera", "no face in view", "6 fps < 10"


@dataclass(frozen=True)
class Blink:
    at: float  # seconds on the detector's own clock (compare with ``BlinkDetector.now()``)


class BlinkDetector(Protocol):
    def now(self) -> float:
        """Current time on the clock that ``Blink.at`` uses."""
        ...

    async def check(self) -> VisionCheck:
        """Open the camera if needed and look for a face for a short moment. Never raises."""
        ...

    async def wait_for_blink(self) -> Blink:
        """Arm now and return the participant's first blink. Raises BlinkDetectorError.

        Cancel the call to disarm the detector.
        """
        ...

    async def close(self) -> None:
        """Release the camera (safe to call twice)."""
        ...
