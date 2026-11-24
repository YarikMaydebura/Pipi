"""The hand-test tool ``blink_check`` with a fake detector (never opens the webcam)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pipi_brain.tools import blink_check
from pipi_brain.vision.base import Blink, BlinkDetectorError, VisionCheck


class ScriptedDetector:
    """Blinks after the given delays (real time, short); an exception ends the camera."""

    def __init__(self, vision: VisionCheck, script: list[object]) -> None:
        self._vision = vision
        self._script = list(script)
        self.closed = 0

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def check(self) -> VisionCheck:
        return self._vision

    async def wait_for_blink(self) -> Blink:
        item = self._script.pop(0) if self._script else None
        if isinstance(item, BaseException):
            raise item
        if item is None:
            await asyncio.Event().wait()
        await asyncio.sleep(float(item))  # type: ignore[arg-type]
        return Blink(at=self.now())

    async def close(self) -> None:
        self.closed += 1


async def test_run_check_prints_check_and_each_blink() -> None:
    lines: list[str] = []
    detector = ScriptedDetector(VisionCheck(ok=True, fps=30.0), [0.01, 0.01])
    code = await blink_check.run_check(detector, seconds=0.2, emit=lines.append)
    assert code == 0
    assert any("ok=True fps=30 -> game mode detect" in line for line in lines)
    assert sum("blink" in line and "at +" in line for line in lines) == 2
    assert lines[-1] == "Summary: 2 blink(s) in 0.2 s"
    assert detector.closed == 1


async def test_run_check_without_camera_exits_1_and_closes() -> None:
    lines: list[str] = []
    detector = ScriptedDetector(VisionCheck(ok=False, reason="mediapipe not installed"), [])
    code = await blink_check.run_check(detector, seconds=1.0, emit=lines.append)
    assert code == 1
    assert "game mode pretend (mediapipe not installed)" in lines[1]
    assert detector.closed == 1


async def test_run_check_reports_a_camera_failure() -> None:
    lines: list[str] = []
    script: list[object] = [0.01, BlinkDetectorError("camera failed: unplugged")]
    detector = ScriptedDetector(VisionCheck(ok=False, fps=6.0, reason="6 fps < 10"), script)
    code = await blink_check.run_check(detector, seconds=1.0, emit=lines.append)
    assert code == 1
    assert lines[-1] == "[FAIL] camera failed: unplugged"
    assert detector.closed == 1


def test_main_rejects_a_missing_config(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert blink_check.main(["--config", str(tmp_path / "nope.yaml")]) == 2
    assert "Error" in capsys.readouterr().err


def test_main_rejects_non_positive_seconds(capsys: pytest.CaptureFixture[str]) -> None:
    assert blink_check.main(["--config", "x.yaml", "--seconds", "0"]) == 2
    assert "--seconds" in capsys.readouterr().err
