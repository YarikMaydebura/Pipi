"""Draw Pipi's eye images (512x512 PNG, transparent background) into out/eyes/.

Same image contract as desktop-pet/src/renderer/eyes/drawEyes.ts:
- one square image = the robot's LEFT eye (EyeL, +X) seen from the front; the image's right
  side is the eye's outer side. EyeR shows the same image mirrored.
- the eye is a rounded rectangle ~40% x 60% of the image, teal #3FE0C5 with a soft glow and a
  white highlight; the background stays transparent (the face screen behind it is dark).
Kept simple and high-contrast so the same images can be shown on a physical eye display.

Run on its own (build_pipi.py also calls it):
    "$BLENDER_PATH" --background --python assets/pipi3d/eye_images.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
EYES_DIR = HERE / "out" / "eyes"
SIZE = 512

TEAL = {"light": "#b8fff1", "mid": "#3fe0c5", "deep": "#17a58f"}
BRIGHT_TEAL = {"light": "#e4fffa", "mid": "#52f2d8", "deep": "#10a891"}
HEART_PINK = {"light": "#ffd3dc", "mid": "#ff7a93", "deep": "#e2456a"}
GAZE_SHIFT = (0.13, 0.10)  # eye travel for gaze = 1, relative to the image size


@dataclass(frozen=True)
class EyeStyle:
    width: float = 0.40
    height: float = 0.60
    openness: float = 1.0  # 0 closed .. 1 open
    gaze: tuple[float, float] = (0.0, 0.0)  # +x outward, +y down
    lid_tilt: float = 0.0  # radians; > 0 lowers the outer side of the upper lid
    glow: float = 0.7
    palette: dict[str, str] | None = None
    shape: str = "box"  # box | closed | arc
    smile: float = 0.0  # 0 = flat bottom; > 0 lifts the bottom edge into an upward curve ("smiling eyes")


BASE = EyeStyle(palette=TEAL)
SMILING_EYES = 0.22  # depth of the bottom curve, relative to the eye height
STATES: dict[str, EyeStyle] = {
    "idle": replace(BASE, smile=SMILING_EYES),
    "blink": replace(BASE, shape="closed"),
    "happy": replace(BASE, shape="arc", glow=0.85),
    "thinking": replace(BASE, height=0.54, gaze=(0.5, -0.55), glow=0.55),
    "surprised": replace(BASE, width=0.50, height=0.70, glow=0.9),
    "sleepy": replace(BASE, openness=0.28, gaze=(0.0, 0.35), glow=0.35),
    "determined": replace(BASE, openness=0.6, palette=BRIGHT_TEAL, lid_tilt=-0.35, glow=0.9),
    "love": replace(BASE, shape="heart", palette=HEART_PINK, glow=0.9),
}


# --------------------------------------------------------------------------------------
# Tiny signed-distance rasteriser (canvas coordinates: x right, y down, in pixels)
# --------------------------------------------------------------------------------------

YY, XX = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32) + 0.5


def hex_rgb(value: str) -> np.ndarray:
    v = int(value[1:], 16)
    return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], dtype=np.float32) / 255.0


def coverage(sdf: np.ndarray) -> np.ndarray:
    """Anti-aliased coverage from a signed distance in pixels (negative = inside)."""
    return np.clip(0.5 - sdf, 0.0, 1.0)


def sdf_round_rect(cx: float, cy: float, w: float, h: float, r: float) -> np.ndarray:
    qx = np.abs(XX - cx) - (w / 2 - r)
    qy = np.abs(YY - cy) - (h / 2 - r)
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    return outside + np.minimum(np.maximum(qx, qy), 0) - r


def sdf_ellipse(cx: float, cy: float, rx: float, ry: float, angle: float = 0.0) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    dx, dy = XX - cx, YY - cy
    u, v = dx * c + dy * s, -dx * s + dy * c
    k = np.hypot(u / rx, v / ry)
    return (k - 1.0) * min(rx, ry)


def sdf_arc(cx: float, cy: float, r: float, a0: float, a1: float, half_width: float) -> np.ndarray:
    """Stroked circular arc from angle a0 to a1 (canvas angles), with round caps."""
    dx, dy = XX - cx, YY - cy
    ang = np.mod(np.arctan2(dy, dx), 2 * math.pi)
    lo, hi = np.mod(a0, 2 * math.pi), np.mod(a1, 2 * math.pi)
    inside = (ang >= lo) & (ang <= hi) if lo <= hi else (ang >= lo) | (ang <= hi)
    ring = np.abs(np.hypot(dx, dy) - r)
    caps = np.minimum(
        np.hypot(XX - (cx + r * math.cos(a0)), YY - (cy + r * math.sin(a0))),
        np.hypot(XX - (cx + r * math.cos(a1)), YY - (cy + r * math.sin(a1))),
    )
    return np.where(inside, ring, caps) - half_width


def blur(mask: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur (for the glow)."""
    if sigma < 0.5:
        return mask
    radius = int(sigma * 3)
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    k /= k.sum()
    out = np.apply_along_axis(lambda row: np.convolve(row, k, mode="same"), 1, mask)
    return np.apply_along_axis(lambda col: np.convolve(col, k, mode="same"), 0, out)


def over(dst: np.ndarray, rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Composite a colour layer (straight alpha) over an RGBA image (straight alpha)."""
    a_out = alpha + dst[..., 3] * (1 - alpha)
    safe = np.where(a_out > 1e-6, a_out, 1.0)
    rgb_out = (rgb * alpha[..., None] + dst[..., :3] * (dst[..., 3] * (1 - alpha))[..., None]) / safe[..., None]
    return np.concatenate([rgb_out, a_out[..., None]], axis=-1)


# --------------------------------------------------------------------------------------
# Eye drawing
# --------------------------------------------------------------------------------------


def eye_box(style: EyeStyle) -> tuple[float, float, float, float]:
    cx = SIZE / 2 + style.gaze[0] * SIZE * GAZE_SHIFT[0]
    cy = SIZE / 2 + style.gaze[1] * SIZE * GAZE_SHIFT[1]
    return cx, cy, style.width * SIZE, style.height * SIZE


def lid_mask(style: EyeStyle, cx: float, cy: float, h: float) -> np.ndarray:
    """1 where the eye is open: below the (tilted) upper lid, above the lower lid."""
    closed = 1.0 - style.openness
    top = cy - h / 2 + h * closed * 0.8
    bottom = cy + h / 2 - h * closed * 0.2
    top_line = top + math.tan(style.lid_tilt) * (XX - cx)
    return coverage(top_line - YY) * coverage(YY - bottom)


def gradient(palette: dict[str, str], top: float, bottom: float) -> np.ndarray:
    t = np.clip((YY - top) / max(1.0, bottom - top), 0, 1)[..., None]
    light, mid, deep = (hex_rgb(palette[k]) for k in ("light", "mid", "deep"))
    upper = light + (mid - light) * np.clip(t * 2, 0, 1)
    return np.where(t < 0.5, upper, mid + (deep - mid) * np.clip(t * 2 - 1, 0, 1))


def with_glow(img: np.ndarray, shape: np.ndarray, style: EyeStyle) -> np.ndarray:
    halo = blur(shape, SIZE * 0.04 * style.glow) * 0.9 * style.glow
    return over(img, np.broadcast_to(hex_rgb(style.palette["mid"]), img[..., :3].shape), np.clip(halo, 0, 1))


def smile_mask(style: EyeStyle, cx: float, cy: float, w: float, h: float) -> np.ndarray:
    """Cut a big circle out of the bottom so the lower edge curves up like a smiling eye."""
    if style.smile <= 0:
        return np.ones((SIZE, SIZE), np.float32)
    depth = style.smile * h
    radius = (w * w / 4 + depth * depth) / (2 * depth) * 1.15  # circle through the bottom corners
    center_y = cy + h / 2 - depth + radius
    return 1.0 - coverage(sdf_ellipse(cx, center_y, radius, radius))


def draw_box_eye(style: EyeStyle) -> np.ndarray:
    cx, cy, w, h = eye_box(style)
    shape = coverage(sdf_round_rect(cx, cy, w, h, min(w, h) * 0.45)) * lid_mask(style, cx, cy, h)
    shape = shape * smile_mask(style, cx, cy, w, h)
    img = with_glow(np.zeros((SIZE, SIZE, 4), np.float32), shape, style)
    img = over(img, gradient(style.palette, cy - h / 2, cy + h / 2), shape)
    top = cy - h / 2
    white = np.ones((SIZE, SIZE, 3), np.float32)
    spot = coverage(sdf_ellipse(cx - 0.18 * w, top + 0.24 * h, 0.14 * w, 0.10 * h, -0.35))
    img = over(img, white, spot * shape * 0.95)
    dot = coverage(sdf_ellipse(cx + 0.17 * w, top + 0.72 * h, 0.06 * w, 0.06 * w))
    return over(img, white, dot * shape * 0.7)


def draw_closed_eye(style: EyeStyle) -> np.ndarray:
    cx, cy, w, h = eye_box(style)
    thickness = SIZE * 0.06
    shape = coverage(sdf_round_rect(cx, cy + 0.25 * h, 1.2 * w, thickness, thickness / 2))
    img = with_glow(np.zeros((SIZE, SIZE, 4), np.float32), shape, style)
    return over(img, np.broadcast_to(hex_rgb(style.palette["mid"]), (SIZE, SIZE, 3)), shape)


def draw_arc_eye(style: EyeStyle) -> np.ndarray:
    """Happy eye: a glowing upward arc, like '^'."""
    cx, cy, _, _ = eye_box(style)
    r, y = SIZE * 0.22, cy + SIZE * 0.12
    shape = coverage(sdf_arc(cx, y, r, math.pi * 1.1, math.pi * 1.9, SIZE * 0.065))
    img = with_glow(np.zeros((SIZE, SIZE, 4), np.float32), shape, style)
    img = over(img, gradient(style.palette, y - r, y - r * 0.4), shape)
    shine = coverage(sdf_arc(cx, y - SIZE * 0.02, r, math.pi * 1.25, math.pi * 1.55, SIZE * 0.02))
    return over(img, np.ones((SIZE, SIZE, 3), np.float32), shine * shape * 0.8)


def sdf_heart(cx: float, cy: float, size: float) -> np.ndarray:
    """Approximate signed distance (pixels) to the classic heart curve
    (x^2 + y^2 - 1)^3 - x^2 y^3 = 0, scaled to `size` and centred at (cx, cy)."""
    x = (XX - cx) / size
    y = -(YY - cy) / size + 0.15  # canvas y points down; nudge so the heart is centred
    f = (x * x + y * y - 1) ** 3 - x * x * y ** 3
    gy, gx = np.gradient(f)
    grad = np.hypot(gx, gy) * size + 1e-6
    return f / grad * size


def draw_heart_eye(style: EyeStyle) -> np.ndarray:
    """Love eyes: a glowing pink heart with a white highlight."""
    cx, cy, w, _ = eye_box(style)
    size = w * 0.62
    shape = coverage(sdf_heart(cx, cy, size))
    img = with_glow(np.zeros((SIZE, SIZE, 4), np.float32), shape, style)
    img = over(img, gradient(style.palette, cy - size, cy + size), shape)
    spot = coverage(sdf_ellipse(cx - 0.42 * size, cy - 0.55 * size, 0.18 * size, 0.13 * size, -0.5))
    return over(img, np.ones((SIZE, SIZE, 3), np.float32), spot * shape * 0.9)


DRAWERS = {"box": draw_box_eye, "closed": draw_closed_eye, "arc": draw_arc_eye, "heart": draw_heart_eye}


def render_state(style: EyeStyle) -> np.ndarray:
    return DRAWERS[style.shape](style)


def save_png(rgba: np.ndarray, path: Path) -> None:
    """Blender images are stored bottom-up, so flip the canvas rows."""
    img = bpy.data.images.new(path.stem, SIZE, SIZE, alpha=True)
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def write_all(out_dir: Path = EYES_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, style in STATES.items():
        path = out_dir / f"{name}.png"
        save_png(render_state(style), path)
        paths[name] = path
    print(f"[pipi] eye images written to {out_dir}: {', '.join(paths)}")
    return paths


if __name__ == "__main__":
    write_all()
