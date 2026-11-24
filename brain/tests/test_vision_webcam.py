"""The capture thread with a scripted camera (vision/webcam.py): no real webcam is opened."""

from __future__ import annotations

import asyncio
import threading

import pytest

from pipi_brain.vision.webcam import CameraError, OpenCvFrameSource, WebcamCapture

from .test_vision_fakes import ScriptedSource, no_camera


async def started(source: ScriptedSource) -> WebcamCapture:
    capture = WebcamCapture(source)
    await capture.start(open_timeout_s=1.0, first_frame_timeout_s=1.0)
    return capture


async def test_capture_delivers_newer_frames_with_capture_times() -> None:
    capture = await started(ScriptedSource([0.31, 0.32, 0.33]))
    try:
        first = await capture.next_frame(after_index=0, timeout_s=1.0)
        second = await capture.next_frame(after_index=first.index, timeout_s=1.0)
        assert second.index > first.index
        assert second.captured_at > first.captured_at
        assert capture.latest() is not None
    finally:
        await capture.close()


async def test_capture_measures_fps() -> None:
    capture = await started(ScriptedSource(fps=100.0))
    try:
        await asyncio.sleep(0.3)
        assert 30.0 < capture.fps() < 150.0
    finally:
        await capture.close()


async def test_close_stops_the_thread_releases_and_forgets_the_frame() -> None:
    source = ScriptedSource()
    capture = await started(source)
    assert capture.running
    await capture.close()
    await capture.close()  # safe twice
    assert not capture.running
    assert source.released >= 1
    assert capture.latest() is None
    assert not any(t.name == "webcam-capture" and t.is_alive() for t in threading.enumerate())


async def test_open_failure_is_a_readable_camera_error() -> None:
    capture = WebcamCapture(ScriptedSource(open_error=no_camera()))
    with pytest.raises(CameraError, match="cannot open camera"):
        await capture.start(open_timeout_s=1.0, first_frame_timeout_s=1.0)
    assert not capture.running


async def test_driver_exception_on_open_becomes_camera_error() -> None:
    capture = WebcamCapture(ScriptedSource(open_error=RuntimeError("driver exploded")))
    with pytest.raises(CameraError, match="driver exploded"):
        await capture.start(open_timeout_s=1.0, first_frame_timeout_s=1.0)


async def test_open_that_hangs_times_out() -> None:
    capture = WebcamCapture(ScriptedSource(open_delay_s=0.5))
    with pytest.raises(CameraError, match="did not open within"):
        await capture.start(open_timeout_s=0.05, first_frame_timeout_s=1.0)


async def test_camera_that_opens_but_never_delivers_frames() -> None:
    # macOS without camera permission: the device opens, every read fails.
    source = ScriptedSource(failed_reads=True)
    capture = WebcamCapture(source)
    with pytest.raises(CameraError, match="Privacy"):
        await capture.start(open_timeout_s=1.0, first_frame_timeout_s=0.2)
    assert not capture.running
    assert source.released >= 1


async def test_camera_that_dies_raises_on_next_frame() -> None:
    capture = await started(ScriptedSource(die_after=3))
    try:
        with pytest.raises(CameraError, match="unplugged"):
            for _ in range(10):
                frame = await capture.next_frame(after_index=10_000, timeout_s=1.0)
                assert frame is None  # never reached: no frame has such an index
    finally:
        await capture.close()


async def test_next_frame_times_out_when_frames_stall() -> None:
    capture = await started(ScriptedSource(fps=2.0))
    try:
        latest = capture.latest()
        assert latest is not None
        with pytest.raises(CameraError, match="no camera frame"):
            await capture.next_frame(after_index=latest.index + 100, timeout_s=0.05)
    finally:
        await capture.close()


async def test_next_frame_on_a_stopped_capture_fails_fast() -> None:
    capture = WebcamCapture(ScriptedSource())
    with pytest.raises(CameraError, match="not running"):
        await capture.next_frame(after_index=0, timeout_s=1.0)


def test_opencv_source_without_open_reads_nothing() -> None:
    source = OpenCvFrameSource(0)  # constructing it never touches the camera
    assert source.read() is None
    source.release()
