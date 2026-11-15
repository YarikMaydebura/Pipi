// Paints Pipi's mouth (a MouthFrame) into a square 2D canvas context: a small emissive teal
// line with the same colours and glow as the eyes, on a transparent background.
// Image contract (shared with the Blender model): one square image fills the "Mouth" mesh,
// UVs cover the full 0–1 square (glTF V: v = 0 is the top), not mirrored.
import { PALETTES } from '../eyes/eyeFrame';
import { withAlpha } from '../eyes/drawEyes';
import type { MouthFrame } from './mouthFrame';
import {
  BIG_SMILE,
  FLAT,
  GLOW_SIGMA,
  GRADIENT_BAND,
  SMALL_O,
  SMILE,
  WAVY,
  wavyPoints,
  type MouthShape,
} from './mouthShapes';

/** The subset of CanvasRenderingContext2D the drawer uses (lets tests pass a recorder). */
export type MouthContext = Pick<
  CanvasRenderingContext2D,
  | 'save'
  | 'restore'
  | 'beginPath'
  | 'closePath'
  | 'arc'
  | 'ellipse'
  | 'roundRect'
  | 'moveTo'
  | 'lineTo'
  | 'fill'
  | 'stroke'
  | 'clearRect'
  | 'createLinearGradient'
  | 'fillStyle'
  | 'strokeStyle'
  | 'lineWidth'
  | 'lineCap'
  | 'lineJoin'
  | 'shadowBlur'
  | 'shadowColor'
>;

const TEAL = PALETTES.teal;
const HALO_ALPHA = 0.9;
const TAU = Math.PI * 2;

type Painter = (ctx: MouthContext, size: number, open: number) => void;

const PAINTERS: Readonly<Record<MouthShape, Painter>> = {
  smile(ctx, size) {
    ctx.lineWidth = SMILE.halfWidth * 2 * size;
    ctx.beginPath();
    ctx.arc(SMILE.cx * size, SMILE.cy * size, SMILE.r * size, SMILE.from, SMILE.to);
    ctx.stroke();
  },
  big_smile(ctx, size, open) {
    const { cx, top, rx, ry } = BIG_SMILE;
    ctx.beginPath();
    ctx.ellipse(cx * size, top * size, rx * size, Math.max(0.01, ry * open) * size, 0, 0, Math.PI);
    ctx.closePath();
    ctx.fill();
  },
  small_o(ctx, size, open) {
    ctx.lineWidth = SMALL_O.halfWidth * 2 * size;
    ctx.beginPath();
    ctx.arc(SMALL_O.cx * size, SMALL_O.cy * size, SMALL_O.r * open * size, 0, TAU);
    ctx.stroke();
  },
  flat(ctx, size) {
    const { cx, cy, width, halfHeight } = FLAT;
    ctx.beginPath();
    ctx.roundRect(
      (cx - width / 2) * size,
      (cy - halfHeight) * size,
      width * size,
      halfHeight * 2 * size,
      halfHeight * size,
    );
    ctx.fill();
  },
  wavy(ctx, size) {
    const [first, ...rest] = wavyPoints(size);
    if (!first) return;
    ctx.lineWidth = WAVY.halfWidth * 2 * size;
    ctx.beginPath();
    ctx.moveTo(first.x, first.y);
    for (const p of rest) ctx.lineTo(p.x, p.y);
    ctx.stroke();
  },
};

/** Clear the canvas and paint the mouth. `size` is the canvas width = height in pixels. */
export function drawMouth(ctx: MouthContext, frame: MouthFrame, size: number): void {
  ctx.clearRect(0, 0, size, size);
  if (frame.shape === 'off') return; // screen off: nothing glows
  const gradient = ctx.createLinearGradient(
    0,
    GRADIENT_BAND.top * size,
    0,
    GRADIENT_BAND.bottom * size,
  );
  gradient.addColorStop(0, TEAL.light);
  gradient.addColorStop(0.5, TEAL.mid);
  gradient.addColorStop(1, TEAL.deep);

  ctx.save();
  ctx.fillStyle = gradient;
  ctx.strokeStyle = gradient;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  // Canvas shadow blur is about twice the Gaussian sigma used by the Python halo.
  ctx.shadowColor = withAlpha(TEAL.mid, HALO_ALPHA * frame.glow);
  ctx.shadowBlur = size * GLOW_SIGMA * 2;
  PAINTERS[frame.shape](ctx, size, frame.open);
  ctx.restore();
}
