// Outline of a "smiling" eye: the rounded rectangle with a big circle cut out of its bottom, so
// the lower edge curves upward (port of `smile_mask` in assets/pipi3d/eye_images.py).
// Pure geometry in canvas coordinates (x right, y down), so it can be unit-tested.

export interface EyeRect {
  readonly cx: number;
  readonly cy: number;
  readonly w: number;
  readonly h: number;
}

export interface Circle {
  readonly cx: number;
  readonly cy: number;
  readonly r: number;
}

export interface SmileOutline {
  /** The circle removed from the bottom of the eye. */
  readonly cut: Circle;
  /** Where the cut meets the eye's RIGHT side; the left side is its mirror image. */
  readonly meet: { readonly x: number; readonly y: number };
  /** Angle of `meet` on the bottom-right corner arc, or null when it is on the straight side. */
  readonly cornerAngle: number | null;
  /** Angle of `meet` on the cut circle (canvas angles: 0 = right, +π/2 = down). */
  readonly cutAngle: number;
}

/** eye_images.py widens the circle through the bottom corners by this factor (flatter curve). */
const CUT_WIDEN = 1.15;

/** The circle cut out of the bottom: its top sits `smile * h` above the eye's bottom edge. */
export function smileCut(eye: EyeRect, smile: number): Circle {
  const depth = smile * eye.h;
  const r = (((eye.w * eye.w) / 4 + depth * depth) / (2 * depth)) * CUT_WIDEN;
  return { cx: eye.cx, cy: eye.cy + eye.h / 2 - depth + r, r };
}

/** Intersection of the cut with the bottom-right corner circle, on the visible quarter arc. */
function cornerMeet(corner: Circle, cut: Circle): { x: number; y: number } | null {
  const dx = cut.cx - corner.cx;
  const dy = cut.cy - corner.cy;
  const d = Math.hypot(dx, dy);
  if (d === 0) return null;
  const a = (corner.r * corner.r - cut.r * cut.r + d * d) / (2 * d);
  const hSq = corner.r * corner.r - a * a;
  if (hSq < 0) return null;
  const h = Math.sqrt(hSq);
  const px = corner.cx + (a * dx) / d;
  const py = corner.cy + (a * dy) / d;
  const candidates = [
    { x: px + (h * dy) / d, y: py - (h * dx) / d },
    { x: px - (h * dy) / d, y: py + (h * dx) / d },
  ];
  return candidates.find((p) => p.x >= corner.cx - 1e-9 && p.y >= corner.cy - 1e-9) ?? null;
}

/**
 * The smiling outline for an eye with rounded corners of `cornerRadius`, or null when the eye
 * does not smile (or the cut would not touch its sides, which the formula never produces).
 */
export function smileOutline(
  eye: EyeRect,
  cornerRadius: number,
  smile: number,
): SmileOutline | null {
  if (!(smile > 0) || eye.w <= 0 || eye.h <= 0) return null;
  const cut = smileCut(eye, smile);
  const half = eye.w / 2;
  if (cut.r <= half) return null;
  const right = eye.cx + half;
  const bottom = eye.cy + eye.h / 2;
  const sideY = cut.cy - Math.sqrt(cut.r * cut.r - half * half);
  const cutAngleAt = (p: { x: number; y: number }): number =>
    Math.atan2(p.y - cut.cy, p.x - cut.cx);

  if (sideY <= bottom - cornerRadius) {
    const meet = { x: right, y: sideY };
    return { cut, meet, cornerAngle: null, cutAngle: cutAngleAt(meet) };
  }
  const corner = { cx: right - cornerRadius, cy: bottom - cornerRadius, r: cornerRadius };
  const meet = cornerMeet(corner, cut);
  if (!meet) return null;
  const cornerAngle = Math.atan2(meet.y - corner.cy, meet.x - corner.cx);
  return { cut, meet, cornerAngle, cutAngle: cutAngleAt(meet) };
}
