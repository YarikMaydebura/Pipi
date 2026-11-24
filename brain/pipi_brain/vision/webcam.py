"""Webcam capture for the blink detector: a background thread keeps only the latest frame.

Reading a camera blocks (``cv2.VideoCapture.read`` waits for the next frame), so a daemon
thread reads frames and the asyncio loop only picks up the newest one with its capture time
(``time.monotonic``, the detector's clock). Older frames are simply overwritten.

Privacy (CLAUDE.md): frames live in memory only. Nothing here writes a frame to disk, logs
pixel data or sends it anywhere; only the latest frame is kept and it is dropped on close.

``FrameSource`` hides OpenCV so tests drive the capture with fake frames (no camera).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pipi_brain.resilience import describe_error, with_timeout

FPS_WINDOW_FRAMES = 30  # fps = frames over the time span of the last 30 frames
MAX_FAILED_READS = 30  # this many failed reads in a row = the camera is gone
FAILED_READ_PAUSE_S = 0.02
THREAD_JOIN_TIMEOUT_S = 2.0

PERMISSION_HINT = (
    "macOS: System Settings > Privacy & Security > Camera, allow the terminal app; "
    "Windows: Settings > Privacy > Camera, allow desktop apps"
)


class CameraError(Exception):
    """The camera cannot be opened or stopped delivering frames (readable message)."""


@dataclass(frozen=True)
class Frame:
    image: Any  # RGB numpy array (height, width, 3), uint8; memory only, never stored
    captured_at: float  # monotonic seconds when the frame was read
    index: int  # 1, 2, 3 ... in capture order


class FrameSource(Protocol):
    """Blocking camera access; only ever called from the capture thread (or ``to_thread``)."""

    def open(self) -> None:
        """Open the device. Raises CameraError with a readable message."""
        ...

    def read(self) -> Any | None:
        """Block until the next RGB frame; None if this read failed."""
        ...

    def release(self) -> None: ...


class OpenCvFrameSource:
    """The default webcam through OpenCV (imported lazily: optional ``[vision]`` extra)."""

    def __init__(self, index: int = 0, *, width: int = 640, height: int = 480) -> None:
        self._index = index
        self._size = (width, height)
        self._cv2: Any = None
        self._capture: Any = None

    def open(self) -> None:
        try:
            import cv2  # optional dependency
        except ImportError as exc:
            raise CameraError('opencv not installed (pip install -e ".[vision]")') from exc
        self._cv2 = cv2
        # DirectShow opens much faster than the default (MSMF) backend on many Windows laptops.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self._index, backend)
        if not capture.isOpened():
            capture.release()
            raise CameraError(
                f"cannot open camera {self._index}: no camera, used by another app, "
                f"or no permission ({PERMISSION_HINT})"
            )
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._size[0])
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._size[1])
        self._capture = capture

    def read(self) -> Any | None:
        if self._capture is None:
            return None
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            return None
        return self._cv2.cvtColor(bgr, self._cv2.COLOR_BGR2RGB)

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


class WebcamCapture:
    """Reads ``source`` in a daemon thread; ``next_frame`` hands the newest frame to asyncio."""

    def __init__(
        self, source: FrameSource, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._source = source
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._times: deque[float] = deque(maxlen=FPS_WINDOW_FRAMES)
        self._error: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._new_frame = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    async def start(self, *, open_timeout_s: float, first_frame_timeout_s: float) -> None:
        """Open the camera and wait for the first frame. Raises CameraError (never hangs)."""
        if self.running:
            return
        try:
            await with_timeout(asyncio.to_thread(self._source.open), open_timeout_s)
        except TimeoutError as exc:
            raise CameraError(f"the camera did not open within {open_timeout_s:g} s") from exc
        except CameraError:
            raise
        except Exception as exc:  # driver errors from OpenCV
            raise CameraError(f"cannot open the camera: {describe_error(exc)}") from exc
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="webcam-capture", daemon=True)
        self._thread.start()
        try:
            await self.next_frame(after_index=0, timeout_s=first_frame_timeout_s)
        except CameraError as exc:
            await self.close()
            raise CameraError(f"{exc} ({PERMISSION_HINT})") from exc

    def fps(self) -> float:
        """Frames per second the camera delivered recently (0 until two frames arrived)."""
        with self._lock:
            if len(self._times) < 2:
                return 0.0
            span = self._times[-1] - self._times[0]
            return (len(self._times) - 1) / span if span > 0 else 0.0

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    async def next_frame(self, *, after_index: int, timeout_s: float) -> Frame:
        """The newest frame with ``index > after_index``. Raises CameraError on stall/failure."""
        deadline = self._monotonic() + timeout_s
        while True:
            self._new_frame.clear()
            frame = self.latest()
            if frame is not None and frame.index > after_index:
                return frame
            if self._error is not None:
                raise CameraError(self._error)
            if not self.running:
                raise CameraError("the camera is not running")
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise CameraError(f"no camera frame for {timeout_s:g} s")
            with contextlib.suppress(TimeoutError):
                await with_timeout(self._new_frame.wait(), remaining)

    async def close(self) -> None:
        """Stop the thread, release the camera, forget the last frame. Safe to call twice."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            await asyncio.to_thread(thread.join, THREAD_JOIN_TIMEOUT_S)
        with contextlib.suppress(Exception):  # releasing a dead camera must not crash close()
            await asyncio.to_thread(self._source.release)
        with self._lock:
            self._latest = None
            self._times.clear()

    # --- capture thread -----------------------------------------------------------------

    def _run(self) -> None:
        failures = 0
        index = 0
        while not self._stop.is_set():
            try:
                image = self._source.read()
            except Exception as exc:  # a driver error ends the capture with a readable reason
                self._fail(f"camera read failed: {describe_error(exc)}")
                return
            if image is None:
                failures += 1
                if failures >= MAX_FAILED_READS:
                    self._fail(f"the camera stopped delivering frames ({failures} failed reads)")
                    return
                self._stop.wait(FAILED_READ_PAUSE_S)
                continue
            failures = 0
            index += 1
            captured_at = self._monotonic()
            with self._lock:
                self._latest = Frame(image, captured_at, index)
                self._times.append(captured_at)
            self._notify()

    def _fail(self, reason: str) -> None:
        self._error = reason
        self._notify()

    def _notify(self) -> None:
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # the loop is already closed: nobody waits
            loop.call_soon_threadsafe(self._new_frame.set)
