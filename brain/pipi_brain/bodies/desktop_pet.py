"""The desktop pet as a Body: protocol messages over the WebSocket server (server.py).

Timing rules (config ``bodies``):
- every command waits for its ``ack`` (``ack_timeout_s``); eyes / caption / body_config are
  resent ``ack_retries`` times because doing them twice is harmless,
- ``activate`` / ``deactivate`` are acked by the pet when the animation has FINISHED, so they
  wait longer (``migration_timeout_s``),
- ``speak`` waits for the ack, then for ``speech_done`` (audio length, or an estimated reading
  time for captions only, plus ``speech_done_margin_s``).

Audio goes to the pet as a base64 WAV file, which every browser decodes with Web Audio.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable

from pipi_brain.bodies.base import (
    NOT_CONNECTED,
    BodyLog,
    BodyResult,
    Entrance,
    Exit,
    SpeakResult,
)
from pipi_brain.bodies.channel import BodyChannel, BodyLink
from pipi_brain.config import BodiesConfig
from pipi_brain.protocol import (
    Activate,
    BodyConfig,
    BodyToBrain,
    Caption,
    Deactivate,
    Expression,
    Eyes,
    EyeState,
    Hello,
    Motion,
    RobotSide,
    Speak,
)
from pipi_brain.speech.audio_utils import pcm16_to_wav
from pipi_brain.speech.base import SpeechAudio

MIN_CAPTION_S = 1.5  # the pet shows a caption at least this long (mirrors speech/timing.ts)


def encode_audio_wav_b64(audio: SpeechAudio) -> str:
    """PCM16 mono -> complete WAV file -> base64 text (the ``audio_b64`` field)."""
    return base64.b64encode(pcm16_to_wav(audio.pcm16, audio.sample_rate)).decode("ascii")


def caption_seconds(text: str, seconds_per_char: float) -> float:
    """How long a captions-only line is shown (estimated reading time)."""
    return max(MIN_CAPTION_S, len(text) * seconds_per_char)


class DesktopPetBody:
    name = "desktop_pet"

    def __init__(
        self,
        settings: BodiesConfig,
        *,
        robot_side: RobotSide,
        log: BodyLog,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._settings = settings
        self._robot_side = robot_side
        self._clock = clock
        self.channel = BodyChannel(self.name, log)
        self._tasks: set[asyncio.Task[BodyResult]] = set()

    # --- connection (called by the server) -------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.channel.connected

    async def wait_connected(self, timeout_s: float) -> bool:
        return await self.channel.wait_connected(timeout_s)

    def attach(self, link: BodyLink, hello: Hello) -> BodyLink | None:
        """A pet said hello: use it and send it its settings (robot side)."""
        previous = self.channel.attach(link, hello)
        task = asyncio.get_running_loop().create_task(self.send_config())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return previous

    def detach(self, link: BodyLink, reason: str) -> None:
        self.channel.detach(link, reason)

    def receive(self, message: BodyToBrain) -> None:
        self.channel.receive(message)

    def health(self) -> str:
        if not self.connected:
            return NOT_CONNECTED
        return f"connected (pet {self.channel.version})"

    # --- commands --------------------------------------------------------------------------

    async def send_config(self) -> BodyResult:
        return await self.channel.request(
            BodyConfig(robot_side=self._robot_side),
            timeout_s=self._settings.ack_timeout_s,
            retries=self._settings.ack_retries,
        )

    async def activate(self, entrance: Entrance) -> BodyResult:
        return await self.channel.request(
            Activate(entrance=entrance), timeout_s=self._settings.migration_timeout_s
        )

    async def deactivate(self, exit: Exit) -> BodyResult:
        return await self.channel.request(
            Deactivate(exit=exit), timeout_s=self._settings.migration_timeout_s
        )

    async def set_eyes(self, state: EyeState) -> BodyResult:
        return await self.channel.request(
            Eyes(state=state),
            timeout_s=self._settings.ack_timeout_s,
            retries=self._settings.ack_retries,
        )

    async def play_motion(self, name: str) -> BodyResult:
        return await self.channel.request(Motion(name=name), timeout_s=self._settings.ack_timeout_s)

    async def show_caption(self, text: str | None) -> BodyResult:
        return await self.channel.request(
            Caption(text=text),
            timeout_s=self._settings.ack_timeout_s,
            retries=self._settings.ack_retries,
        )

    async def speak(
        self, text: str, audio: SpeechAudio | None, expression: Expression = "idle"
    ) -> SpeakResult:
        start = self._clock()
        audio_b64 = encode_audio_wav_b64(audio) if audio is not None else None
        message = Speak(text=text, audio_b64=audio_b64, expression=expression)
        done_future = self.channel.expect_speech_done(message.id)
        sent = await self.channel.request(message, timeout_s=self._settings.ack_timeout_s)
        if not sent.ok:
            self.channel.forget_speech_done(message.id)
            return SpeakResult(
                delivered=False, finished=False, error=sent.error, elapsed_ms=self._ms(start)
            )
        expected_s = (
            audio.duration_s
            if audio is not None
            else caption_seconds(text, self._settings.caption_s_per_char)
        )
        timeout_s = expected_s + self._settings.speech_done_margin_s
        done, error = await self.channel.wait_speech_done(message.id, done_future, timeout_s)
        if done is None:
            self.channel.log_speak_error(message.id, error or "unknown")
            return SpeakResult(
                delivered=True, finished=False, error=error, elapsed_ms=self._ms(start)
            )
        return SpeakResult(
            delivered=True,
            finished=True,
            duration_ms=done.duration_ms,
            elapsed_ms=self._ms(start),
        )

    def _ms(self, start: float) -> int:
        return round((self._clock() - start) * 1000)
