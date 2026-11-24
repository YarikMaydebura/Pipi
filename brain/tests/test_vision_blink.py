"""Blink logic with synthetic EAR numbers: no camera, no model (vision/blink.py)."""

from __future__ import annotations

import math

import pytest

from pipi_brain.vision.blink import (
    LEFT_EYE,
    RIGHT_EYE,
    BlinkSettings,
    BlinkTracker,
    RunningBaseline,
    eye_aspect_ratio,
    face_ear,
    judge_check,
    percentile,
)

OPEN = 0.30
CLOSED = 0.10


def eye_points(height: float, width: float = 1.0) -> list[tuple[float, float]]:
    """Six eye points p1..p6 whose EAR is exactly ``height / width``."""
    return [
        (0.0, 0.0),
        (width / 3, -height / 2),
        (2 * width / 3, -height / 2),
        (width, 0.0),
        (2 * width / 3, height / 2),
        (width / 3, height / 2),
    ]


def feed(tracker: BlinkTracker, ears: list[float | None], *, fps: float, t0: float = 0.0):
    """Feed one EAR per frame; returns the blink start times that were reported."""
    found = []
    for i, ear in enumerate(ears):
        started = tracker.update(t0 + i / fps, ear)
        if started is not None:
            found.append(started)
    return found


def warm(tracker: BlinkTracker, *, ear: float = OPEN, frames: int = 30, fps: float = 30.0):
    assert feed(tracker, [ear] * frames, fps=fps) == []
    return frames / fps  # time of the next frame


# --- EAR -------------------------------------------------------------------------------------


def test_eye_aspect_ratio_is_height_over_width() -> None:
    assert eye_aspect_ratio(eye_points(0.3)) == pytest.approx(0.3)
    assert eye_aspect_ratio(eye_points(0.6, width=2.0)) == pytest.approx(0.3)
    assert eye_aspect_ratio(eye_points(0.0)) == pytest.approx(0.0)


def test_eye_aspect_ratio_needs_six_points_and_survives_zero_width() -> None:
    with pytest.raises(ValueError):
        eye_aspect_ratio([(0.0, 0.0)] * 5)
    assert eye_aspect_ratio([(1.0, 1.0)] * 6) == 0.0


def face_landmarks(left: float, right: float, width: int, height: int) -> list[tuple[float, float]]:
    """478 normalized points with both eyes placed at pixel EARs ``left`` / ``right``."""
    points = [(0.5, 0.5)] * 478
    for indices, ear, x0 in ((LEFT_EYE, left, 380.0), (RIGHT_EYE, right, 200.0)):
        for idx, (x, y) in zip(indices, eye_points(ear * 60.0, width=60.0), strict=True):
            points[idx] = ((x0 + x) / width, (240.0 + y) / height)
    return points


def test_face_ear_averages_both_eyes_in_pixel_space() -> None:
    points = face_landmarks(0.30, 0.20, width=640, height=480)
    assert face_ear(points, 640, 480) == pytest.approx(0.25)


def test_face_ear_uses_image_size_not_normalized_units() -> None:
    points = face_landmarks(0.30, 0.30, width=640, height=480)
    assert face_ear(points, 640, 480) == pytest.approx(0.30)
    assert face_ear(points, 480, 480) != pytest.approx(0.30)  # wrong aspect -> wrong EAR


# --- baseline --------------------------------------------------------------------------------


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0
    assert percentile([1.0, 2.0], 90) == pytest.approx(1.9)
    assert percentile([7.0], 90) == 7.0


def test_baseline_waits_for_enough_samples_then_ignores_blinks() -> None:
    baseline = RunningBaseline(window=50, q=90, min_samples=10)
    for _ in range(9):
        baseline.add(OPEN)
    assert baseline.value is None
    baseline.add(CLOSED)  # a blink among open values barely moves a high percentile
    assert baseline.value == pytest.approx(OPEN)


def test_baseline_follows_recent_values_only() -> None:
    baseline = RunningBaseline(window=20, q=90, min_samples=5)
    for _ in range(20):
        baseline.add(0.35)
    for _ in range(20):
        baseline.add(0.22)
    assert baseline.value == pytest.approx(0.22)


# --- tracker ---------------------------------------------------------------------------------


def test_a_normal_blink_reports_the_time_the_eye_closed() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    found = feed(tracker, [CLOSED] * 4 + [OPEN] * 3, fps=30.0, t0=t)
    assert found == [pytest.approx(t)]


def test_blink_is_reported_only_when_the_eye_opens_again() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    assert feed(tracker, [CLOSED] * 5, fps=30.0, t0=t) == []
    assert tracker.update(t + 0.2, OPEN) == pytest.approx(t)


def test_one_noisy_frame_at_30_fps_is_not_a_blink() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    assert feed(tracker, [CLOSED, OPEN, OPEN], fps=30.0, t0=t) == []


def test_one_closed_frame_at_10_fps_is_a_blink() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker, fps=10.0)
    assert feed(tracker, [CLOSED, OPEN], fps=10.0, t0=t) == [pytest.approx(t)]


def test_small_dips_and_the_hysteresis_band_are_not_blinks() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    squint = OPEN * 0.75  # between close (70 %) and reopen (80 %): never closed
    assert feed(tracker, [squint] * 10 + [OPEN] * 3, fps=30.0, t0=t) == []


def test_eye_stays_closed_inside_the_hysteresis_band() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    half_open = OPEN * 0.75  # not yet open again: the blink goes on
    found = feed(tracker, [CLOSED, CLOSED, half_open, half_open, OPEN], fps=30.0, t0=t)
    assert found == [pytest.approx(t)]


@pytest.mark.parametrize("open_ear", [0.20, 0.30, 0.40])
def test_threshold_is_relative_to_the_persons_own_eyes(open_ear: float) -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker, ear=open_ear)
    closed = open_ear * 0.5
    assert feed(tracker, [closed] * 3 + [open_ear] * 2, fps=30.0, t0=t) == [pytest.approx(t)]


def test_narrow_eyes_open_are_not_mistaken_for_a_blink() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker, ear=0.18)  # 0.18 would be "closed" with a fixed 0.2 threshold
    assert feed(tracker, [0.18] * 60, fps=30.0, t0=t) == []


def test_no_blinks_before_the_baseline_is_warm() -> None:
    tracker = BlinkTracker(BlinkSettings(baseline_min_samples=10))
    assert feed(tracker, [OPEN] * 5 + [CLOSED] * 3 + [OPEN] * 2, fps=30.0) == []


def test_eyes_kept_shut_count_once_without_reopening() -> None:
    tracker = BlinkTracker(BlinkSettings(long_closure_s=1.0))
    t = warm(tracker)
    found = feed(tracker, [CLOSED] * 45 + [OPEN] * 3, fps=30.0, t0=t)
    assert found == [pytest.approx(t)]  # reported at 1 s, not again when the eyes open


def test_reset_ignores_a_blink_already_in_progress() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    feed(tracker, [CLOSED] * 3, fps=30.0, t0=t)
    tracker.reset()  # armed while the eye is closed: this closure is stale
    assert feed(tracker, [CLOSED] * 2 + [OPEN] * 2, fps=30.0, t0=t + 0.1) == []
    t2 = t + 1.0
    assert feed(tracker, [CLOSED] * 3 + [OPEN], fps=30.0, t0=t2) == [pytest.approx(t2)]


def test_reset_keeps_the_baseline() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    tracker.reset()
    assert tracker.baseline.value == pytest.approx(OPEN)
    found = feed(tracker, [OPEN, CLOSED, CLOSED, OPEN], fps=30.0, t0=t)
    assert found == [pytest.approx(t + 1 / 30)]


def test_losing_the_face_mid_blink_drops_that_closure() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    assert feed(tracker, [CLOSED, CLOSED, None, OPEN, OPEN], fps=30.0, t0=t) == []


def test_several_blinks_in_a_row() -> None:
    tracker = BlinkTracker(BlinkSettings())
    t = warm(tracker)
    one = [CLOSED] * 3 + [OPEN] * 12
    found = feed(tracker, one * 3, fps=30.0, t0=t)
    assert found == [pytest.approx(t + k * 15 / 30) for k in range(3)]


# --- check verdict ---------------------------------------------------------------------------


def frame_times(fps: float, frames: int) -> list[float]:
    return [i / fps for i in range(frames)]


def test_judge_check_ok_with_face_and_enough_fps() -> None:
    result = judge_check(frame_times(25, 25), 25, min_fps=10, min_face_share=0.5)
    assert result.ok and result.reason is None
    assert math.isclose(result.fps, 25.0)


def test_judge_check_low_fps_means_pretend() -> None:
    result = judge_check(frame_times(6, 6), 6, min_fps=10, min_face_share=0.5)
    assert not result.ok
    assert result.reason == "6 fps < 10"


def test_judge_check_no_face_means_pretend() -> None:
    result = judge_check(frame_times(30, 30), 3, min_fps=10, min_face_share=0.5)
    assert not result.ok
    assert result.reason == "no face in view"


def test_judge_check_with_no_frames_is_not_ok() -> None:
    result = judge_check([], 0, min_fps=10, min_face_share=0.5)
    assert not result.ok
    assert result.fps == 0.0
    assert "no face in view" in (result.reason or "")
