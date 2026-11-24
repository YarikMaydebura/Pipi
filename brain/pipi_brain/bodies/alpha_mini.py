"""The real Alpha Mini as a Body, over RidK (Robots in de Klas, WAMP).

Same interface as the pet and the fake robot (``bodies/base.py``), so the session logic cannot
tell them apart. It uses ONLY calls from the course's example scripts:

- ``speak``: the robot's built-in voice, ``rie.dialogue.say`` (Pipi's TTS audio is not used,
  so the robot sounds different from the pet). The call is treated as finished when it returns,
  but never sooner than an estimated speaking time, so lines do not run over each other if the
  robot answers before it has finished talking.
- ``play_motion``: a move from ``config/alpha_mini.yaml`` (behaviors + head keyframes). Like
  the fake robot, it is acknowledged at once and plays in the background; a new motion
  replaces the running one. Unknown names fail, like an unknown motion on the fake robot.
- ``activate`` / ``deactivate``: the ``wake_up`` / ``sleep`` moves, awaited to the end.
- ``set_eyes`` / ``show_caption``: no verified RidK call for eye LEDs, and the robot has no
  screen: accepted and ignored (logged once), so games and speech go on normally.
- ``stop``: cancels the running move and stops audio (``rom.actuator.audio.stop``).

The RidK session comes and goes (``attach`` / ``detach``, called by ``bodies/ridk.py``);
nothing here raises: every problem is a failed result and a log entry.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pipi_brain.bodies.alpha_mini_moves import MoveLibrary, MoveStep
from pipi_brain.bodies.base import (
    NOT_CONNECTED,
    BodyLog,
    BodyResult,
    Entrance,
    Exit,
    SpeakResult,
)
from pipi_brain.protocol import Expression, EyeState
from pipi_brain.resilience import CallOutcome, timed_call, with_timeout
from pipi_brain.speech.base import SpeechAudio

SAY_URI = "rie.dialogue.say"
AUDIO_STOP_URI = "rom.actuator.audio.stop"
WAKE_MOVE = "wake_up"
SLEEP_MOVE = "sleep"


class RidkSession(Protocol):
    """The part of an autobahn session the body uses."""

    async def call(self, uri: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class AlphaMiniSettings:
    call_timeout_s: float  # robot.ridk_call_timeout_s
    stop_timeout_s: float  # bodies.stop_timeout_s
    speech_s_per_char: float  # least speaking time per character (bodies.caption_s_per_char)


class AlphaMiniBody:
    name = "alpha_mini"

    def __init__(
        self,
        moves: MoveLibrary,
        settings: AlphaMiniSettings,
        *,
        log: BodyLog,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._moves = moves
        self._settings = settings
        self._log = log
        self._clock = clock
        self._sleep = sleep
        self._session: RidkSession | None = None
        self._joined = asyncio.Event()
        self._motion: asyncio.Task[BodyResult] | None = None
        self._ignored: set[str] = set()  # unsupported commands already logged once

    # --- connection (called by bodies/ridk.py) ---------------------------------------------

    def attach(self, session: RidkSession) -> None:
        self._session = session
        self._joined.set()
        self._log("body_connect", {"body": self.name, "via": "ridk"})

    def detach(self, reason: str) -> None:
        if self._session is None:
            return
        self._session = None
        self._joined.clear()
        self._cancel_motion()
        self._log("body_disconnect", {"body": self.name, "reason": reason})

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def wait_connected(self, timeout_s: float) -> bool:
        if self.connected:
            return True
        with contextlib.suppress(TimeoutError):
            await with_timeout(self._joined.wait(), timeout_s)
        return self.connected

    def health(self) -> str:
        return "connected (alpha mini via RidK)" if self.connected else NOT_CONNECTED

    async def close(self) -> None:
        """Stop a running move task (the session is closed by the connector)."""
        task = self._cancel_motion()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # --- commands --------------------------------------------------------------------------

    async def activate(self, entrance: Entrance) -> BodyResult:
        # The robot has one way to appear: it stands up (any entrance plays wake_up).
        return await self._play_now(WAKE_MOVE)

    async def deactivate(self, exit: Exit) -> BodyResult:
        return await self._play_now(SLEEP_MOVE)

    async def speak(
        self, text: str, audio: SpeechAudio | None, expression: Expression = "idle"
    ) -> SpeakResult:
        start = self._clock()
        if not text.strip():  # the "stop talking" workaround sends an empty line
            return SpeakResult(delivered=True, finished=True, elapsed_ms=0)
        outcome = await self._call(SAY_URI, text=text)
        if not outcome.ok:
            self._log("body_error", {"body": self.name, "command": "speak", "error": outcome.error})
            return SpeakResult(
                delivered=False, finished=False, error=outcome.error, elapsed_ms=self._ms(start)
            )
        least_s = len(text) * self._settings.speech_s_per_char
        if (left_s := least_s - (self._clock() - start)) > 0:
            await self._sleep(left_s)
        elapsed = self._ms(start)
        return SpeakResult(delivered=True, finished=True, duration_ms=elapsed, elapsed_ms=elapsed)

    async def set_eyes(self, state: EyeState) -> BodyResult:
        return self._ignore("eyes")

    async def show_caption(self, text: str | None) -> BodyResult:
        return self._ignore("caption")

    async def play_motion(self, name: str) -> BodyResult:
        steps = self._moves.get(name)
        if steps is None:
            return BodyResult(ok=False, error=f"unknown motion {name!r}")
        if not self.connected:
            return BodyResult(ok=False, error=NOT_CONNECTED)
        self._cancel_motion()
        task = asyncio.get_running_loop().create_task(self._run(name, steps))
        task.add_done_callback(self._motion_done)
        self._motion = task
        return BodyResult(ok=True)

    async def stop(self) -> BodyResult:
        """Emergency stop: end the running move at once and stop any audio."""
        start = self._clock()
        await self.close()
        if not self.connected:
            return BodyResult(ok=False, error=NOT_CONNECTED, elapsed_ms=self._ms(start))
        outcome = await timed_call(
            lambda: self._session_call(AUDIO_STOP_URI), self._settings.stop_timeout_s
        )
        return BodyResult(
            ok=outcome.ok,
            error=outcome.error,
            elapsed_ms=self._ms(start),
            timed_out=outcome.timed_out,
        )

    # --- inside ----------------------------------------------------------------------------

    async def _play_now(self, name: str) -> BodyResult:
        steps = self._moves.get(name)
        if steps is None:
            return BodyResult(ok=False, error=f"no {name!r} move in alpha_mini.yaml")
        if not self.connected:
            return BodyResult(ok=False, error=NOT_CONNECTED)
        await self.close()
        return await self._run(name, steps)

    async def _run(self, name: str, steps: tuple[MoveStep, ...]) -> BodyResult:
        """Play the steps in order; each takes at least its ``duration_s``."""
        start = self._clock()
        for index, step in enumerate(steps, start=1):
            step_start = self._clock()
            uri, kwargs = step.call()
            outcome = await self._call(uri, **kwargs)
            if not outcome.ok:
                error = f"move {name!r} step {index}: {outcome.error}"
                self._log("body_error", {"body": self.name, "command": "motion", "error": error})
                return BodyResult(
                    ok=False, error=error, elapsed_ms=self._ms(start), timed_out=outcome.timed_out
                )
            if (left_s := step.duration_s - (self._clock() - step_start)) > 0:
                await self._sleep(left_s)
        return BodyResult(ok=True, elapsed_ms=self._ms(start))

    async def _call(self, uri: str, **kwargs: Any) -> CallOutcome[Any]:
        return await timed_call(
            lambda: self._session_call(uri, **kwargs), self._settings.call_timeout_s
        )

    async def _session_call(self, uri: str, **kwargs: Any) -> Any:
        session = self._session
        if session is None:
            raise ConnectionError(NOT_CONNECTED)
        return await session.call(uri, **kwargs)

    def _cancel_motion(self) -> asyncio.Task[BodyResult] | None:
        task, self._motion = self._motion, None
        if task is not None and not task.done():
            task.cancel()
            return task
        return None

    def _motion_done(self, task: asyncio.Task[BodyResult]) -> None:
        if self._motion is task:
            self._motion = None

    def _ignore(self, command: str) -> BodyResult:
        if command not in self._ignored:
            self._ignored.add(command)
            self._log(
                "body_unsupported",
                {"body": self.name, "command": command, "note": "no verified RidK call: ignored"},
            )
        return BodyResult(ok=True)

    def _ms(self, start: float) -> int:
        return round((self._clock() - start) * 1000)
