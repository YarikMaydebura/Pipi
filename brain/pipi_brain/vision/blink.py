"""The real blink detector for the staring contest: webcam + MediaPipe face landmarks.

How a blink is found (docs/GAMES.md §3.3):

1. MediaPipe's face landmarker gives 478 points per face. Six points around each eye give the
   eye aspect ratio, EAR = (|p2-p6| + |p3-p5|) / (2 |p1-p4|): about 0.25-0.35 when the eye is
   open, close to 0.1 when it is shut. The two eyes are averaged.
2. Eye shapes differ, so there is no fixed threshold: ``RunningBaseline`` keeps the recent EAR
   values and takes their 90th percentile as this person's open-eye value.
3. ``BlinkTracker``: the eye counts as closed below 70 % of the baseline and as open again
   above 80 % (the gap stops flicker). A blink = closed, then open again, for at least 50 ms
   (one noisy frame at 30 fps is shorter). Eyes kept shut for 1 s also count, right away.
   After arming, an open eye must be seen first, so a blink already going on is not counted.
   ``Blink.at`` is the capture time of the first closed frame.

Only the pure logic above is tested with numbers; the camera and the model sit behind
``FrameSource`` (vision/webcam.py) and ``FaceModel``. mediapipe and cv2 are imported lazily:
without the ``[vision]`` extra ``check()`` says "mediapipe not installed" -> pretend mode.
Privacy: frames are only in memory (see vision/webcam.py); only EAR numbers leave this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from pipi_brain.resilience import describe_error, with_timeout
from pipi_brain.speech.model_cache import ensure_model
from pipi_brain.vision.base import Blink, BlinkDetectorError, VisionCheck
from pipi_brain.vision.webcam import CameraError, FrameSource, OpenCvFrameSource, WebcamCapture

# Face-mesh indices p1..p6 per eye: corner, upper, upper, corner, lower, lower.
RIGHT_EYE = (33, 160, 158, 133, 153, 144)
LEFT_EYE = (362, 385, 387, 263, 373, 380)

# Pinned model version + checksum; downloaded once into the gitignored <repo>/cache/models/.
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
    "float16/1/face_landmarker.task"
)
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "cache" / "models"
MEDIAPIPE_MISSING = "mediapipe not installed"


# --- pure logic ------------------------------------------------------------------------------


def eye_aspect_ratio(points: Sequence[tuple[float, float]]) -> float:
    """EAR of one eye from its six points p1..p6 (pixel coordinates)."""
    if len(points) != 6:
        raise ValueError(f"an eye needs 6 points, got {len(points)}")
    p1, p2, p3, p4, p5, p6 = points
    width = math.dist(p1, p4)
    if width <= 0:
        return 0.0
    return (math.dist(p2, p6) + math.dist(p3, p5)) / (2.0 * width)


def face_ear(landmarks: Sequence[tuple[float, float]], width: int, height: int) -> float:
    """Mean EAR of both eyes from normalized face-mesh points (x, y in 0..1 of the image)."""

    def eye(indices: Sequence[int]) -> float:
        return eye_aspect_ratio(
            [(landmarks[i][0] * width, landmarks[i][1] * height) for i in indices]
        )

    return (eye(LEFT_EYE) + eye(RIGHT_EYE)) / 2.0


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, ``q`` in 0..100 (``values`` must not be empty)."""
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100.0
    low = math.floor(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


@dataclass(frozen=True)
class BlinkSettings:
    """Tuning of the detector (defaults work for most faces at 10-30 fps)."""

    close_ratio: float = 0.70  # EAR below 70 % of the open-eye baseline = closed
    reopen_ratio: float = 0.80  # and above 80 % = open again (hysteresis)
    min_blink_s: float = 0.05  # first closed frame -> first open frame, shorter = noise
    long_closure_s: float = 1.0  # eyes kept shut this long count as a blink at once
    baseline_window: int = 90  # recent EAR values the baseline is taken from
    baseline_percentile: float = 90.0
    baseline_min_samples: int = 10  # no blinks before the baseline has this many values
    check_s: float = 1.0  # check(): judged over the last second of frames
    check_warmup_s: float = 0.5  # check(): frames right after opening are skipped (dark)
    check_max_s: float = 3.0  # check(): give up after this long (then: pretend mode)
    min_face_share: float = 0.5  # check(): face in at least half of the frames
    open_timeout_s: float = 10.0  # camera open (Windows can be slow)
    first_frame_timeout_s: float = 5.0
    frame_timeout_s: float = 2.0  # no new frame for this long = camera gone
    model_timeout_s: float = 60.0  # import + first download (3.7 MB) + load of the model
    process_timeout_s: float = 2.0  # landmarks of one frame


class RunningBaseline:
    """The person's open-eye EAR: a high percentile of the recent values."""

    def __init__(self, window: int, q: float, min_samples: int) -> None:
        self._values: deque[float] = deque(maxlen=window)
        self._q = q
        self._min_samples = min_samples

    def add(self, ear: float) -> None:
        self._values.append(ear)

    @property
    def value(self) -> float | None:
        if len(self._values) < self._min_samples:
            return None
        return percentile(self._values, self._q)


class BlinkTracker:
    """State machine over an EAR time series; ``update`` returns a blink's start time."""

    def __init__(self, settings: BlinkSettings) -> None:
        self._s = settings
        self.baseline = RunningBaseline(
            settings.baseline_window, settings.baseline_percentile, settings.baseline_min_samples
        )
        self._state = "wait_open"  # wait_open -> open -> closed -> open ...
        self._closed_since = 0.0
        self._reported = False

    def reset(self) -> None:
        """Arm: forget any closure in progress (an open eye must come first); keep the baseline."""
        self._state = "wait_open"

    def update(self, t: float, ear: float | None) -> float | None:
        """Feed one frame (``ear`` None = no face). Returns the blink's start time or None."""
        if ear is None:  # face lost: a closure we cannot see the end of is not a blink
            self._state = "wait_open"
            return None
        base = self.baseline.value
        self.baseline.add(ear)
        if base is None:
            return None
        is_closed = ear < base * self._s.close_ratio
        is_open = ear >= base * self._s.reopen_ratio
        if self._state != "closed":
            if self._state == "open" and is_closed:
                self._state, self._closed_since, self._reported = "closed", t, False
            elif is_open:
                self._state = "open"
            return None
        return self._closed_update(t, is_open)

    def _closed_update(self, t: float, is_open: bool) -> float | None:
        duration = t - self._closed_since
        if is_open:
            self._state = "open"
            if not self._reported and duration >= self._s.min_blink_s:
                return self._closed_since
            return None
        if not self._reported and duration >= self._s.long_closure_s:
            self._reported = True
            return self._closed_since
        return None


def judge_check(
    capture_times: Sequence[float], faces: int, *, min_fps: float, min_face_share: float
) -> VisionCheck:
    """Detect mode or pretend: processed frames per second and how often a face was seen."""
    frames = len(capture_times)
    span = capture_times[-1] - capture_times[0] if frames >= 2 else 0.0
    fps = (frames - 1) / span if span > 0 else 0.0
    reasons = []
    if faces == 0 or faces < frames * min_face_share:
        reasons.append("no face in view")
    if fps < min_fps:
        reasons.append(f"{fps:.0f} fps < {min_fps:g}")
    return VisionCheck(ok=not reasons, fps=round(fps, 1), reason="; ".join(reasons) or None)


# --- MediaPipe face model --------------------------------------------------------------------


class FaceModel(Protocol):
    def eye_ratio(self, image: Any, timestamp_ms: int) -> float | None:
        """Mean EAR of the first face in an RGB image; None if there is no face. Blocking."""
        ...

    def close(self) -> None: ...


class MediaPipeFaceModel:
    """MediaPipe Tasks ``FaceLandmarker`` in VIDEO mode (tracks between frames: faster)."""

    def __init__(self, landmarker: Any, mp: Any) -> None:
        self._landmarker = landmarker
        self._mp = mp
        self._lock = threading.Lock()  # a cancelled call may still run in its thread
        self._last_ms = -1

    def eye_ratio(self, image: Any, timestamp_ms: int) -> float | None:
        with self._lock:
            stamp = max(timestamp_ms, self._last_ms + 1)  # VIDEO mode: strictly increasing
            self._last_ms = stamp
            picture = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=image)
            result = self._landmarker.detect_for_video(picture, stamp)
        if not result.face_landmarks:
            return None
        points = [(p.x, p.y) for p in result.face_landmarks[0]]
        height, width = image.shape[:2]
        return face_ear(points, width, height)

    def close(self) -> None:
        with self._lock:
            self._landmarker.close()


def load_face_model(model_dir: Path, download_timeout_s: float) -> FaceModel:
    """Import mediapipe, fetch the model once, build the landmarker. Blocking: use a thread."""
    try:
        import mediapipe as mp  # optional dependency ([vision] extra)
        from mediapipe.tasks.python import BaseOptions, vision
    except ImportError as exc:
        raise BlinkDetectorError(MEDIAPIPE_MISSING) from exc
    model_path = ensure_model(
        model_dir / "face_landmarker.task",
        url=FACE_MODEL_URL,
        sha256=FACE_MODEL_SHA256,
        timeout_s=download_timeout_s,
    )
    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
    )
    return MediaPipeFaceModel(vision.FaceLandmarker.create_from_options(options), mp)


# --- the detector ----------------------------------------------------------------------------


class WebcamBlinkDetector:
    """``BlinkDetector`` on the laptop webcam. The clock is ``time.monotonic``."""

    def __init__(
        self,
        *,
        min_fps: float,
        settings: BlinkSettings | None = None,
        source: FrameSource | None = None,
        model_factory: Callable[[], FaceModel] | None = None,
        camera_index: int = 0,
        model_dir: Path = DEFAULT_MODEL_DIR,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_fps = min_fps
        self._s = settings or BlinkSettings()
        self._monotonic = monotonic
        self._capture = WebcamCapture(
            source or OpenCvFrameSource(camera_index), monotonic=monotonic
        )
        self._model_factory = model_factory or partial(
            load_face_model, model_dir, self._s.model_timeout_s
        )
        self._model: FaceModel | None = None
        self.tracker = BlinkTracker(self._s)

    def now(self) -> float:
        return self._monotonic()

    async def check(self) -> VisionCheck:
        try:
            await self._ensure_ready()
            return await self._sample_until_ok()
        except BlinkDetectorError as exc:
            return VisionCheck(ok=False, reason=str(exc))
        except Exception as exc:  # check() never raises: anything odd -> pretend mode
            return VisionCheck(ok=False, reason=describe_error(exc))

    async def wait_for_blink(self) -> Blink:
        await self._ensure_ready()
        armed_at = self.now()
        self.tracker.reset()
        latest = self._capture.latest()
        last_index = latest.index if latest is not None else 0
        while True:
            frame = await self._next_frame(last_index)
            last_index = frame.index
            if frame.captured_at < armed_at:  # stale: captured before arming
                continue
            ear = await self._process(frame.image, frame.captured_at)
            started = self.tracker.update(frame.captured_at, ear)
            if started is not None:
                return Blink(at=started)

    async def close(self) -> None:
        await self._capture.close()
        model, self._model = self._model, None
        if model is not None:
            with contextlib.suppress(Exception):  # closing must never fail the game
                await asyncio.to_thread(model.close)

    async def _ensure_ready(self) -> None:
        """Model first (no camera if mediapipe is missing), then the camera."""
        if self._model is None:
            self._model = await self._load_model()
        if self._capture.running:
            return
        try:
            await self._capture.start(
                open_timeout_s=self._s.open_timeout_s,
                first_frame_timeout_s=self._s.first_frame_timeout_s,
            )
        except CameraError as exc:
            raise BlinkDetectorError(f"no camera: {exc}") from exc

    async def _load_model(self) -> FaceModel:
        timeout_s = self._s.model_timeout_s
        try:
            return await with_timeout(asyncio.to_thread(self._model_factory), timeout_s)
        except TimeoutError as exc:
            raise BlinkDetectorError(f"face model not ready within {timeout_s:g} s") from exc
        except BlinkDetectorError:
            raise
        except Exception as exc:  # download failed, broken install ...
            raise BlinkDetectorError(f"face model failed: {describe_error(exc)}") from exc

    async def _sample_until_ok(self) -> VisionCheck:
        """Skip the warm-up, then judge the last ``check_s`` of frames until it is good
        enough or ``check_max_s`` is over (a dark first frame or a late face is no reason
        for pretend mode). Also warms up the open-eye baseline."""
        s = self._s
        start = self.now()
        latest = self._capture.latest()
        last_index = latest.index if latest is not None else 0
        window: deque[tuple[float, bool]] = deque()
        verdict = VisionCheck(ok=False, reason="no frames")
        while self.now() - start < s.check_max_s:
            frame = await self._next_frame(last_index)
            last_index = frame.index
            ear = await self._process(frame.image, frame.captured_at)
            self.tracker.update(frame.captured_at, ear)
            if frame.captured_at - start < s.check_warmup_s:
                continue
            window.append((frame.captured_at, ear is not None))
            while window and frame.captured_at - window[0][0] > s.check_s:
                window.popleft()
            if frame.captured_at - start < s.check_warmup_s + s.check_s:
                continue  # not a full window yet
            verdict = judge_check(
                [t for t, _ in window],
                sum(face for _, face in window),
                min_fps=self._min_fps,
                min_face_share=s.min_face_share,
            )
            if verdict.ok:
                return verdict
        return verdict

    async def _next_frame(self, after_index: int) -> Any:
        try:
            return await self._capture.next_frame(
                after_index=after_index, timeout_s=self._s.frame_timeout_s
            )
        except CameraError as exc:
            raise BlinkDetectorError(f"camera failed: {exc}") from exc

    async def _process(self, image: Any, captured_at: float) -> float | None:
        model = self._model
        if model is None:
            raise BlinkDetectorError("the detector is closed")
        call = asyncio.to_thread(model.eye_ratio, image, round(captured_at * 1000))
        try:
            return await with_timeout(call, self._s.process_timeout_s)
        except TimeoutError as exc:
            raise BlinkDetectorError("face landmarks too slow") from exc
        except Exception as exc:
            raise BlinkDetectorError(f"face landmarks failed: {describe_error(exc)}") from exc
