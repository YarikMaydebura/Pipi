"""Pause, countdowns and safe points: the three timing rules of the session.

- ``PauseState``: WoZ ``pause`` freezes every timer. Timers count *active* time only
  (clock time minus the time spent paused).
- ``Countdown``: a pausable, extendable timer (focus, break, silence, phase limits).
- ``SafePoints``: stretches that must never be cut in half (an utterance, a migration).
  "WoZ always wins at the next safe point": an interrupt waits until no such stretch is
  running, and meanwhile stops new ones from starting, then cancels the phase.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pipi_brain.phases.clock import Clock, first_of
from pipi_brain.protocol import TimerInfo

EPSILON_S = 1e-6


class PauseState:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._paused_since: float | None = None
        self._paused_total = 0.0
        self._running = asyncio.Event()
        self._running.set()
        self._paused = asyncio.Event()

    @property
    def paused(self) -> bool:
        return self._paused_since is not None

    def pause(self) -> bool:
        """Returns False if already paused."""
        if self._paused_since is not None:
            return False
        self._paused_since = self._clock.now()
        self._running.clear()
        self._paused.set()
        return True

    def resume(self) -> bool:
        """Returns False if not paused."""
        if self._paused_since is None:
            return False
        self._paused_total += self._clock.now() - self._paused_since
        self._paused_since = None
        self._paused.clear()
        self._running.set()
        return True

    def active_now(self) -> float:
        """Clock time without the paused stretches (stands still while paused)."""
        now = self._clock.now()
        frozen = now - self._paused_since if self._paused_since is not None else 0.0
        return now - self._paused_total - frozen

    async def wait_running(self) -> None:
        await self._running.wait()

    async def wait_paused(self) -> None:
        await self._paused.wait()


class Countdown:
    def __init__(self, name: str, total_s: float, pause: PauseState, clock: Clock) -> None:
        self.name = name
        self._total_s = total_s
        self._pause = pause
        self._clock = clock
        self._start = pause.active_now()

    @property
    def total_s(self) -> float:
        return self._total_s

    @property
    def remaining_s(self) -> float:
        return max(0.0, self._start + self._total_s - self._pause.active_now())

    @property
    def expired(self) -> bool:
        return self.remaining_s <= EPSILON_S

    def extend(self, seconds: float) -> None:
        self._total_s += seconds

    async def wait_until_remaining(self, threshold_s: float = 0.0) -> None:
        """Return once at most ``threshold_s`` is left (pause and extend are respected)."""
        while True:
            await self._pause.wait_running()
            left = self.remaining_s - threshold_s
            if left <= EPSILON_S:
                return
            await first_of(self._clock.sleep(left), self._pause.wait_paused())

    async def wait_expired(self) -> None:
        await self.wait_until_remaining(0.0)

    def info(self) -> TimerInfo:
        return TimerInfo(
            name=self.name, remaining_s=round(self.remaining_s, 1), total_s=self._total_s
        )


class SafePoints:
    def __init__(self) -> None:
        self._depth = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._pending = 0
        self._released = asyncio.Event()

    @property
    def busy(self) -> bool:
        return self._depth > 0

    @asynccontextmanager
    async def critical(self) -> AsyncIterator[None]:
        """A stretch that an interrupt must not cut (nested stretches are fine)."""
        while self._pending and self._depth == 0:
            await self._released.wait()  # an interrupt is waiting: start nothing new
        self._depth += 1
        self._idle.clear()
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                self._idle.set()

    async def interrupt(self, task: asyncio.Task[Any]) -> None:
        """Cancel ``task`` at the next safe point and wait until it has stopped."""
        self._pending += 1
        try:
            while self._depth > 0:
                await self._idle.wait()
            task.cancel()
        finally:
            self._pending -= 1
            if self._pending == 0:
                self._released.set()
                self._released = asyncio.Event()
        await asyncio.wait([task])
