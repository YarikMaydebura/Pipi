"""WebcamBlinkDetector against a scripted camera and a fake face model (no webcam, no model).

One test runs the real MediaPipe landmarker on a synthetic black image (no camera): it is
skipped when the optional ``[vision]`` extra is not installed (CI).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

import pytest

from pipi_brain.vision.base import BlinkDetector, BlinkDetectorError
from pipi_brain.vision.blink import (
    DEFAULT_MODEL_DIR,
    MEDIAPIPE_MISSING,
    BlinkSettings,
    WebcamBlinkDetector,
    load_face_model,
)

from .test_vision_fakes import CLOSED, OPEN, FakeFaceModel, ScriptedSource, no_camera

FAST = BlinkSettings(check_s=0.2, first_frame_timeout_s=1.0, frame_timeout_s=0.5)


def detector_with(
    source: ScriptedSource, model: FakeFaceModel | None = None, *, min_fps: float = 10.0
) -> WebcamBlinkDetector:
    face = model or FakeFaceModel()
    return WebcamBlinkDetector(
        min_fps=min_fps, settings=FAST, source=source, model_factory=lambda: face
    )


def files_in(folder: Path) -> list[Path]:
    return list(folder.iterdir())


def test_real_detector_matches_the_contract() -> None:
    detector: BlinkDetector = detector_with(ScriptedSource())
    assert detector.now() > 0


async def test_check_ok_with_a_face_and_fast_frames() -> None:
    detector = detector_with(ScriptedSource(fps=100.0))
    try:
        result = await detector.check()
        assert result.ok, result.reason
        assert result.fps >= 10
        assert detector.tracker.baseline.value == pytest.approx(OPEN)  # warmed up by check
    finally:
        await detector.close()


async def test_check_without_a_face_means_pretend() -> None:
    detector = detector_with(ScriptedSource(tail=None))
    try:
        result = await detector.check()
        assert not result.ok
        assert result.reason == "no face in view"
    finally:
        await detector.close()


async def test_check_with_a_slow_camera_means_pretend() -> None:
    detector = detector_with(ScriptedSource(fps=100.0), min_fps=500.0)
    try:
        result = await detector.check()
        assert not result.ok
        assert "fps < 500" in (result.reason or "")
    finally:
        await detector.close()


async def test_check_without_camera_never_raises() -> None:
    detector = detector_with(ScriptedSource(open_error=no_camera()))
    result = await detector.check()
    assert not result.ok
    assert result.fps == 0.0
    assert (result.reason or "").startswith("no camera: cannot open camera 0")
    await detector.close()


async def test_check_without_mediapipe_does_not_open_the_camera(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "mediapipe", None)  # import mediapipe -> ImportError
    source = ScriptedSource()
    detector = WebcamBlinkDetector(min_fps=10, settings=FAST, source=source, model_dir=tmp_path)
    result = await detector.check()
    assert not result.ok
    assert result.reason == MEDIAPIPE_MISSING
    assert source.opened == 0
    assert files_in(tmp_path) == []  # nothing downloaded either
    await detector.close()


async def test_check_reports_a_failing_model_factory() -> None:
    def broken() -> FakeFaceModel:
        raise OSError("disk full")

    detector = WebcamBlinkDetector(
        min_fps=10, settings=FAST, source=ScriptedSource(), model_factory=broken
    )
    result = await detector.check()
    assert not result.ok
    assert "face model failed" in (result.reason or "")
    assert "disk full" in (result.reason or "")


async def test_wait_for_blink_returns_the_first_blink_after_arming() -> None:
    source = ScriptedSource(fps=100.0)
    detector = detector_with(source)
    try:
        assert (await detector.check()).ok
        waiting = asyncio.create_task(detector.wait_for_blink())
        await asyncio.sleep(0.1)
        armed_before = detector.now()
        source.push([CLOSED] * 10 + [OPEN] * 5)
        blink = await asyncio.wait_for(waiting, 2.0)
        assert armed_before <= blink.at <= detector.now()
    finally:
        await detector.close()


async def test_blinks_before_arming_are_stale() -> None:
    source = ScriptedSource([OPEN] * 30 + [CLOSED] * 10 + [OPEN] * 5, fps=100.0)
    detector = detector_with(source)
    try:
        assert (await detector.check()).ok
        # wait until the whole scripted blink was captured, then arm
        assert await asyncio.to_thread(source.wait_for_reads, 60, 5.0)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(detector.wait_for_blink(), 0.3)
    finally:
        await detector.close()


async def test_wait_for_blink_without_check_still_works_once_warm() -> None:
    source = ScriptedSource([OPEN] * 20 + [CLOSED] * 10 + [OPEN] * 5, fps=100.0)
    detector = detector_with(source)
    try:
        blink = await asyncio.wait_for(detector.wait_for_blink(), 2.0)
        assert blink.at <= detector.now()
    finally:
        await detector.close()


async def test_cancel_disarms_and_close_releases_everything() -> None:
    source = ScriptedSource(fps=100.0)
    model = FakeFaceModel()
    detector = detector_with(source, model)
    waiting = asyncio.create_task(detector.wait_for_blink())
    await asyncio.sleep(0.1)
    waiting.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await waiting
    await detector.close()
    await detector.close()  # safe twice
    assert source.released >= 1
    assert model.closed


async def test_camera_dying_while_armed_raises_detector_error() -> None:
    detector = detector_with(ScriptedSource(fps=100.0, die_after=20))
    try:
        with pytest.raises(BlinkDetectorError, match="camera failed"):
            await asyncio.wait_for(detector.wait_for_blink(), 2.0)
    finally:
        await detector.close()


async def test_wait_for_blink_without_camera_raises_detector_error() -> None:
    detector = detector_with(ScriptedSource(open_error=no_camera()))
    with pytest.raises(BlinkDetectorError, match="no camera"):
        await detector.wait_for_blink()


async def test_model_error_while_armed_raises_detector_error() -> None:
    detector = detector_with(ScriptedSource(), FakeFaceModel(error=RuntimeError("bad graph")))
    try:
        with pytest.raises(BlinkDetectorError, match="bad graph"):
            await asyncio.wait_for(detector.wait_for_blink(), 2.0)
    finally:
        await detector.close()


def test_mediapipe_pipeline_initialises_and_finds_no_face_in_a_black_image() -> None:
    """Real MediaPipe + model (downloaded once into the gitignored cache), no camera."""
    pytest.importorskip("mediapipe")
    np = pytest.importorskip("numpy")
    try:
        model = load_face_model(DEFAULT_MODEL_DIR, download_timeout_s=60.0)
    except Exception as exc:  # offline machine: the model cannot be fetched
        pytest.skip(f"face model unavailable: {exc}")
    try:
        black = np.zeros((480, 640, 3), dtype=np.uint8)
        assert model.eye_ratio(black, 0) is None
        assert model.eye_ratio(black, 0) is None  # same timestamp again is fine (VIDEO mode)
    finally:
        model.close()
