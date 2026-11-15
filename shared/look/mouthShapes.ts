// Pipi's mouth shapes as plain numbers, ported from assets/pipi3d/mouth_images.py.
// Every length is relative to the square mouth image (1 = the image's width), canvas
// coordinates (x right, y down, angles clockwise from +x). The canvas drawer (drawMouth.ts)
// and the 2D fallback's SVG (fallback/fallbackMouth.ts) both read these, so they match.

export const MOUTH_SHAPES = ['smile', 'big_smile', 'small_o', 'flat', 'wavy'] as const;
export type MouthShape = (typeof MOUTH_SHAPES)[number];

const C = 0.5; // centre of the image
/** Half line width, chosen so the mouth still reads when the pet is small. */
export const STROKE = 0.06;
/** Python GLOW: strength of the soft teal halo. */
export const MOUTH_GLOW = 0.8;
/** Halo blur (Gaussian sigma) relative to the image size. */
export const GLOW_SIGMA = 0.035;
/** The fill gradient runs from the light teal (top) to the deep teal (bottom) over this band. */
export const GRADIENT_BAND = { top: C - 0.2, bottom: C + 0.2 } as const;

const SMILE_R = 0.3;

/** Default: a thick stroked arc, the lower part of a circle. */
export const SMILE = {
  cx: C,
  cy: C - 0.72 * SMILE_R,
  r: SMILE_R,
  from: Math.PI * 0.18,
  to: Math.PI * 0.82,
  halfWidth: STROKE,
} as const;

/** Open happy mouth: a filled half-ellipse, flat on top, round at the bottom. */
export const BIG_SMILE = {
  cx: C,
  top: C - 0.4 * SMILE_R,
  rx: SMILE_R,
  ry: SMILE_R * 0.95,
} as const;

/** Surprised / thinking "o": a stroked ring. */
export const SMALL_O = { cx: C, cy: C, r: 0.13, halfWidth: STROKE * 0.85 } as const;

/** Sleepy: a short bar with round ends. */
export const FLAT = { cx: C, cy: C, width: 0.4, halfHeight: STROKE } as const;

/** Nervous: one and a half sine waves. */
export const WAVY = {
  x0: C - 0.24,
  x1: C + 0.24,
  cy: C,
  amplitude: 0.045,
  cycles: 1.5,
  points: 64,
  halfWidth: STROKE * 0.85,
} as const;

export interface Point {
  readonly x: number;
  readonly y: number;
}

/** The sampled wavy line, scaled to an image of `size` pixels. */
export function wavyPoints(size: number): Point[] {
  const { x0, x1, cy, amplitude, cycles, points } = WAVY;
  return Array.from({ length: points }, (_, i) => {
    const t = i / (points - 1);
    return {
      x: (x0 + (x1 - x0) * t) * size,
      y: (cy + amplitude * Math.sin(t * Math.PI * 2 * cycles)) * size,
    };
  });
}

export function isMouthShape(value: string): value is MouthShape {
  return (MOUTH_SHAPES as readonly string[]).includes(value);
}
