// The same mouth shapes as drawMouth.ts, as one SVG path (for the 2D HTML/CSS fallback).
// Pure: returns path data in a `size` × `size` viewBox, no DOM.
import type { MouthFrame } from '@pipi/shared/look';
import {
  BIG_SMILE,
  FLAT,
  SMALL_O,
  SMILE,
  WAVY,
  wavyPoints,
  type MouthShape,
} from '@pipi/shared/look';

export interface MouthPath {
  readonly d: string; // '' = draw nothing
  readonly filled: boolean; // true = fill the path, false = stroke it with round caps
  readonly strokeWidth: number;
}

const fmt = (n: number): string => String(Math.round(n * 100) / 100);

function circlePath(cx: number, cy: number, r: number): string {
  const [x0, x1, y, rr] = [cx - r, cx + r, cy, r].map(fmt);
  return `M${x0} ${y}A${rr} ${rr} 0 1 1 ${x1} ${y}A${rr} ${rr} 0 1 1 ${x0} ${y}Z`;
}

type PathBuilder = (size: number, open: number) => MouthPath;

const BUILDERS: Readonly<Record<MouthShape, PathBuilder>> = {
  smile(size) {
    const { cx, cy, r, from, to, halfWidth } = SMILE;
    const p = (a: number): string =>
      `${fmt((cx + r * Math.cos(a)) * size)} ${fmt((cy + r * Math.sin(a)) * size)}`;
    const rr = fmt(r * size);
    // sweep-flag 1 = clockwise on screen, through the bottom of the circle.
    return {
      d: `M${p(from)}A${rr} ${rr} 0 0 1 ${p(to)}`,
      filled: false,
      strokeWidth: halfWidth * 2 * size,
    };
  },
  big_smile(size, open) {
    const { cx, top, rx, ry } = BIG_SMILE;
    const [x0, x1, y, rX, rY] = [cx - rx, cx + rx, top, rx, Math.max(0.01, ry * open)].map((n) =>
      fmt(n * size),
    );
    return { d: `M${x0} ${y}H${x1}A${rX} ${rY} 0 0 1 ${x0} ${y}Z`, filled: true, strokeWidth: 0 };
  },
  small_o(size, open) {
    const { cx, cy, r, halfWidth } = SMALL_O;
    return {
      d: circlePath(cx * size, cy * size, r * open * size),
      filled: false,
      strokeWidth: halfWidth * 2 * size,
    };
  },
  flat(size) {
    // A stroked line with round caps is the same shape as the rounded bar.
    const { cx, cy, width, halfHeight } = FLAT;
    const half = width / 2 - halfHeight;
    const [x0, x1, y] = [cx - half, cx + half, cy].map((n) => fmt(n * size));
    return { d: `M${x0} ${y}H${x1}`, filled: false, strokeWidth: halfHeight * 2 * size };
  },
  wavy(size) {
    const d = wavyPoints(size)
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${fmt(p.x)} ${fmt(p.y)}`)
      .join('');
    return { d, filled: false, strokeWidth: WAVY.halfWidth * 2 * size };
  },
};

export function mouthSvgPath(frame: MouthFrame, size: number): MouthPath {
  if (frame.shape === 'off') return { d: '', filled: false, strokeWidth: 0 };
  return BUILDERS[frame.shape](size, frame.open);
}
