"""Test helpers for the vision tests: a scripted camera and a face model without MediaPipe.

The "image" of a scripted frame is just ``("ear", value)``: the fake face model reads the
eye aspect ratio straight from it (``None`` = no face). No pixels, no camera, no model.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from pipi_brain.vision.webcam import CameraError

OPEN = 0.30
CLOSED = 0.10


class ScriptedSource:
    """A ``FrameSource`` that plays EAR values at ``fps`` (then ``tail`` forever)."""

    def __init__(
        self,
        ears: list[float | None] | None = None,
        *,
        fps: float = 100.0,
        tail: float | None = OPEN,
        open_error: Exception | None = None,
        open_delay_s: float = 0.0,
        die_after: int | None = None,
        failed_reads: bool = False,
    ) -> None:
        self._ears = list(ears or [])
        self._fps = fps
        self._tail = tail
        self._open_error = open_error
        self._open_delay_s = open_delay_s
        self._die_after = die_after
        self._failed_reads = failed_reads
        self._lock = threading.Condition()
        self.reads = 0
        self.opened = 0
        self.released = 0

    def open(self) -> None:
        time.sleep(self._open_delay_s)
        if self._open_error is not None:
            raise self._open_error
        self.opened += 1

    def read(self) -> Any | None:
        time.sleep(1.0 / self._fps)
        with self._lock:
            self.reads += 1
            self._lock.notify_all()
            if self._failed_reads:
                return None
            if self._die_after is not None and self.reads > self._die_after:
                raise OSError("USB camera unplugged")
            ear = self._ears.pop(0) if self._ears else self._tail
        return ("ear", ear)

    def wait_for_reads(self, count: int, timeout_s: float) -> bool:
        """Block until the camera has delivered ``count`` frames (use via ``to_thread``)."""
        with self._lock:
            return self._lock.wait_for(lambda: self.reads >= count, timeout_s)

    def push(self, ears: list[float | None]) -> None:
        """Queue more EAR values (e.g. a blink after arming)."""
        with self._lock:
            self._ears.extend(ears)

    def release(self) -> None:
        self.released += 1


class FakeFaceModel:
    """``FaceModel`` that reads the EAR out of the scripted frame."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls = 0
        self.closed = False

    def eye_ratio(self, image: Any, timestamp_ms: int) -> float | None:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return image[1]

    def close(self) -> None:
        self.closed = True


def no_camera() -> CameraError:
    return CameraError("cannot open camera 0: no camera, used by another app, or no permission")
