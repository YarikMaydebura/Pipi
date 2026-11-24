"""Try the webcam blink detector by hand (staring contest, docs/GAMES.md §3.3).

Run (from ``brain/``, after ``pip install -e ".[dev,vision]"``):

    python -m pipi_brain.tools.blink_check --config ../config/dev.yaml
    python -m pipi_brain.tools.blink_check --config ../config/dev.yaml --seconds 20 --camera 0

It opens the webcam, prints what ``check()`` says (fps, face found, i.e. would the game use
mode ``detect`` or ``pretend``), then prints one line per detected blink until the time is up.
The first run downloads the face model (3.7 MB) into ``<repo>/cache/models/``. macOS asks
once for camera permission for the terminal app. Frames stay in memory: nothing is saved.
Exit codes: 0 = ran, 1 = camera or model not usable, 2 = bad config.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pipi_brain.config import ConfigError, load_config
from pipi_brain.games.config import load_games_config
from pipi_brain.resilience import with_timeout
from pipi_brain.vision.base import BlinkDetector, BlinkDetectorError
from pipi_brain.vision.blink import WebcamBlinkDetector

DEFAULT_SECONDS = 20.0


async def run_check(
    detector: BlinkDetector, *, seconds: float, emit: Callable[[str], None] = print
) -> int:
    """check(), then blinks for ``seconds``; always closes the detector. Returns the exit code."""
    emit("Opening the webcam (frames stay in memory, nothing is saved) ...")
    try:
        vision = await detector.check()
        mode = "detect" if vision.ok else "pretend"
        reason = f" ({vision.reason})" if vision.reason else ""
        emit(f"check: ok={vision.ok} fps={vision.fps:g} -> game mode {mode}{reason}")
        if vision.fps <= 0:  # no frames at all: camera or model not usable
            return 1
        baseline = getattr(getattr(detector, "tracker", None), "baseline", None)
        if baseline is not None and baseline.value is not None:
            emit(f"open-eye EAR baseline: {baseline.value:.3f}")
        emit(f"Look at the camera and blink now and then ({seconds:g} s) ...")
        count, error = await listen_for_blinks(detector, seconds=seconds, emit=emit)
    finally:
        await detector.close()
    if error is not None:
        emit(f"[FAIL] {error}")
        return 1
    emit(f"Summary: {count} blink(s) in {seconds:g} s")
    return 0


async def listen_for_blinks(
    detector: BlinkDetector, *, seconds: float, emit: Callable[[str], None]
) -> tuple[int, str | None]:
    """Arm again after every blink until ``seconds`` are over: (blinks, error or None)."""
    start = detector.now()
    count = 0
    while (remaining := start + seconds - detector.now()) > 0:
        try:
            blink = await with_timeout(detector.wait_for_blink(), remaining)
        except TimeoutError:
            break
        except BlinkDetectorError as exc:
            return count, str(exc)
        count += 1
        emit(f"  blink {count:>3}  at +{blink.at - start:6.2f} s")
    return count, None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blink_check", description=__doc__.split("\n")[0])
    parser.add_argument("--config", type=Path, required=True, help="e.g. ../config/dev.yaml")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--camera", type=int, default=0, help="camera index (0 = default)")
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        print("Error: --seconds must be > 0", file=sys.stderr)
        return 2
    try:
        loaded = load_config(args.config)
        games = load_games_config(loaded.app.games.games_file)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    detector = WebcamBlinkDetector(
        min_fps=games.staring.min_fps_for_detect, camera_index=args.camera
    )
    return asyncio.run(run_check(detector, seconds=args.seconds))


if __name__ == "__main__":
    sys.exit(main())
