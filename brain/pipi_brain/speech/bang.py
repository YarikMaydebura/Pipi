"""The fast "bang" detector for the quick-draw duel (docs/GAMES.md §3.2).

Speech-to-text is far too slow for a reaction game, so the duel does not transcribe anything:
``MicBangDetector`` reads raw microphone frames (32 ms each) and reports the first one that
is louder than a threshold (a shout, a clap). The time of the bang is the time the frame
was captured, so the measured reaction time does not include our own processing delay.

The half-duplex audio gate is NOT used here on purpose: the gate keeps the microphone
closed for a moment after Pipi speaks, and that would hide a false start right after
"Ready...". Pipi is silent while the detector is armed; frames captured before the detector
was armed (which may contain Pipi's own voice) are dropped instead.

The duel reads frames only while nothing else listens, so the detector and the normal
listening (``AudioInput``) never read the microphone at the same time.
Tests use ``fakes.FakeBangDetector``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pipi_brain.resilience import describe_error
from pipi_brain.speech.audio_utils import rms_dbfs
from pipi_brain.speech.base import Microphone, MicrophoneError


class BangDetectorError(Exception):
    """The detector cannot work (microphone failed): the duel switches to a fallback."""


@dataclass(frozen=True)
class Bang:
    at: float  # seconds on the detector's own clock (compare with ``BangDetector.now()``)
    level_db: float  # loudness of the frame that triggered, dBFS


class BangDetector(Protocol):
    def now(self) -> float:
        """Current time on the clock that ``Bang.at`` uses."""
        ...

    async def wait_for_bang(self) -> Bang:
        """Arm now and return the first loud spike. Raises BangDetectorError.

        Cancel the call to disarm the detector.
        """
        ...


class MicBangDetector:
    """Loudness spike on raw microphone frames: one frame at or above ``threshold_db``."""

    def __init__(
        self,
        microphone: Microphone,
        *,
        threshold_db: float,
        frame_timeout_s: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._microphone = microphone
        self._threshold_db = threshold_db
        self._frame_timeout_s = frame_timeout_s
        self._monotonic = monotonic  # the clock of ``AudioFrame.captured_at``

    def now(self) -> float:
        return self._monotonic()

    async def wait_for_bang(self) -> Bang:
        armed_at = self._monotonic()
        self._microphone.drain()  # audio from before arming is stale (maybe Pipi's own voice)
        while True:
            try:
                frame = await self._microphone.read_frame(self._frame_timeout_s)
            except MicrophoneError as exc:
                raise BangDetectorError(describe_error(exc)) from exc
            if frame.captured_at < armed_at:
                continue
            level = rms_dbfs(frame.samples)
            if level >= self._threshold_db:
                return Bang(at=frame.captured_at, level_db=round(level, 1))
