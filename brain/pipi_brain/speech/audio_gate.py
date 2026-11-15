"""Half-duplex audio gate: Pipi never listens to itself.

While Pipi speaks, and for ``tail_ms`` afterwards, microphone frames are rejected. The check
uses the time a frame was *captured*, so frames recorded during speech but read later are
still rejected. Barge-in (interrupting Pipi) is out of scope.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class AudioGate:
    def __init__(self, tail_ms: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._tail_s = tail_ms / 1000
        self._clock = clock
        self._speaking = False
        self._closed_since = 0.0
        self._open_at = 0.0

    @property
    def is_open(self) -> bool:
        return not self._speaking and self._clock() >= self._open_at

    def close(self) -> None:
        """Pipi starts speaking."""
        self._speaking = True
        self._closed_since = self._clock()

    def open(self) -> None:
        """Pipi stopped speaking; the mic opens again after the tail."""
        self._speaking = False
        self._open_at = self._clock() + self._tail_s

    def accepts(self, captured_at: float) -> bool:
        """Should a frame captured at ``captured_at`` be listened to?"""
        if self._speaking:
            return captured_at < self._closed_since
        return captured_at >= self._open_at

    @contextmanager
    def speaking(self) -> Iterator[None]:
        self.close()
        try:
            yield
        finally:
            self.open()
