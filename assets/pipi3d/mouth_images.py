"""Draw Pipi's mouth images (512x512 PNG, transparent background) into out/mouth/.

The mouth is a small emissive teal line on the dark face screen, same colour and glow as the
eyes (it reuses the rasteriser from eye_images.py). One square image fills the "Mouth" mesh;
the app swaps images to change expression. Default = "smile": Pipi must always look friendly.

Run on its own (build_pipi.py also calls it):
    "$BLENDER_PATH" --background --python assets/pipi3d/mouth_images.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from eye_images import (  # noqa: E402
    SIZE,
    TEAL,
    XX,
    YY,
    coverage,
    gradient,
    hex_rgb,
    over,
    blur,
    save_png,
    sdf_arc,
    sdf_ellipse,
    sdf_round_rect,
)

MOUTH_DIR = HERE / "out" / "mouth"
STROKE = SIZE * 0.06  # half line width, chosen so the mouth still reads at 150 px tall
GLOW = 0.8
C = SIZE / 2


def sdf_polyline(points: np.ndarray, half_width: float) -> np.ndarray:
    """Distance to a sampled curve (N x 2 points, canvas coords), as a stroke."""
    best = np.full((SIZE, SIZE), np.inf, dtype=np.float32)
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:], strict=True):
        dx, dy = x1 - x0, y1 - y0
        t = np.clip(((XX - x0) * dx + (YY - y0) * dy) / (dx * dx + dy * dy), 0, 1)
        best = np.minimum(best, np.hypot(XX - (x0 + t * dx), YY - (y0 + t * dy)))
    return best - half_width


def smile() -> np.ndarray:
    r = SIZE * 0.30
    return coverage(sdf_arc(C, C - 0.72 * r, r, math.pi * 0.18, math.pi * 0.82, STROKE))


def big_smile() -> np.ndarray:
    """Open happy mouth: a filled half-disc (flat top, round bottom)."""
    r = SIZE * 0.30
    top = C - 0.40 * r
    disc = coverage(sdf_ellipse(C, top, r, r * 0.95))
    below = coverage(top - YY)  # keep only the lower half
    return disc * below


def small_o() -> np.ndarray:
    r = SIZE * 0.13
    ring = np.abs(np.hypot(XX - C, YY - C) - r) - STROKE * 0.85
    return coverage(ring)


def flat() -> np.ndarray:
    return coverage(sdf_round_rect(C, C, SIZE * 0.40, STROKE * 2, STROKE))


def wavy() -> np.ndarray:
    xs = np.linspace(C - SIZE * 0.24, C + SIZE * 0.24, 64)
    ys = C + SIZE * 0.045 * np.sin((xs - xs[0]) / (xs[-1] - xs[0]) * 2 * math.pi * 1.5)
    return coverage(sdf_polyline(np.stack([xs, ys], axis=1), STROKE * 0.85))


SHAPES = {"smile": smile, "big_smile": big_smile, "small_o": small_o, "flat": flat, "wavy": wavy}


def render(shape: np.ndarray) -> np.ndarray:
    img = np.zeros((SIZE, SIZE, 4), np.float32)
    mid = np.broadcast_to(hex_rgb(TEAL["mid"]), (SIZE, SIZE, 3))
    halo = np.clip(blur(shape, SIZE * 0.035) * 0.9 * GLOW, 0, 1)
    img = over(img, mid, halo)
    return over(img, gradient(TEAL, C - SIZE * 0.2, C + SIZE * 0.2), shape)


def write_all(out_dir: Path = MOUTH_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, draw in SHAPES.items():
        path = out_dir / f"{name}.png"
        save_png(render(draw()), path)
        paths[name] = path
    print(f"[pipi] mouth images written to {out_dir}: {', '.join(paths)}")
    return paths


if __name__ == "__main__":
    write_all()
