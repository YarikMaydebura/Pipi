// Paints ONE eye (an EyeFrame) into a square 2D canvas context.
//
// Image contract (shared with the Blender model): the square image is the robot's LEFT eye
// ("EyeL", +X) as seen from the front, so the image's right side is the eye's outer side.
// "EyeR" uses the same image with mirrored UVs, which makes expressions symmetric.
// The background stays transparent; the face screen behind the eyes is dark.
import type { EyeFrame } from './eyeFrame';
import { smileOutline, type SmileOutline } from './smileOutline';

/** The subset of CanvasRenderingContext2D the drawer uses (lets tests pass a recorder). */
export type EyeContext = Pick<
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
  | 'clip'
  | 'clearRect'
  | 'createLinearGradient'
  | 'fillStyle'
  | 'strokeStyle'
  | 'lineWidth'
  | 'lineCap'
  | 'globalAlpha'
  | 'shadowBlur'
  | 'shadowColor'
>;

const TAU = Math.PI * 2;
const CLOSED_BELOW = 0.08; // openness under this is drawn as a closed-eye line
const GAZE_SHIFT_X = 0.13; // eye travel for gaze = 1, relative to the image size
const GAZE_SHIFT_Y = 0.1;

/** Convert '#rrggbb' to 'rgba(r,g,b,a)'. */
export function withAlpha(hex: string, alpha: number): string {
  const value = Number.parseInt(hex.slice(1), 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r},${g},${b},${Math.min(1, Math.max(0, alpha))})`;
}

interface EyeBox {
  readonly cx: number;
  readonly cy: number;
  readonly w: number;
  readonly h: number;
}

function eyeBox(frame: EyeFrame, size: number): EyeBox {
  return {
    cx: size / 2 + frame.gazeX * size * GAZE_SHIFT_X,
    cy: size / 2 + frame.gazeY * size * GAZE_SHIFT_Y,
    w: frame.width * size,
    h: frame.height * size,
  };
}

function setGlow(ctx: EyeContext, frame: EyeFrame, size: number): void {
  ctx.shadowColor = withAlpha(frame.palette.mid, 0.9);
  ctx.shadowBlur = size * 0.08 * frame.glow;
}

function clearGlow(ctx: EyeContext): void {
  ctx.shadowBlur = 0;
  ctx.shadowColor = 'rgba(0,0,0,0)';
}

/** Clip to the open part of the eye: below the (tilted) upper lid, above the lower lid. */
function clipToLids(ctx: EyeContext, frame: EyeFrame, box: EyeBox, size: number): void {
  const closed = 1 - frame.openness;
  const top = box.cy - box.h / 2 + box.h * closed * 0.8;
  const bottom = box.cy + box.h / 2 - box.h * closed * 0.2;
  const slope = Math.tan(frame.lidTilt) * size; // outer side (+x) goes down for lidTilt > 0
  ctx.beginPath();
  ctx.moveTo(box.cx - size, top - slope);
  ctx.lineTo(box.cx + size, top + slope);
  ctx.lineTo(box.cx + size, bottom);
  ctx.lineTo(box.cx - size, bottom);
  ctx.closePath();
  ctx.clip();
}

/** The rounded rectangle with its bottom cut by a big circle (see smileOutline.ts). */
function traceSmilingPill(ctx: EyeContext, box: EyeBox, r: number, o: SmileOutline): void {
  const left = box.cx - box.w / 2;
  const right = box.cx + box.w / 2;
  const top = box.cy - box.h / 2;
  const bottom = box.cy + box.h / 2;
  ctx.beginPath();
  ctx.moveTo(left + r, top);
  ctx.arc(right - r, top + r, r, -Math.PI / 2, 0);
  if (o.cornerAngle === null) ctx.lineTo(right, o.meet.y);
  else ctx.arc(right - r, bottom - r, r, 0, o.cornerAngle);
  // Over the top of the cut circle, from the right meeting point to its mirror on the left.
  ctx.arc(o.cut.cx, o.cut.cy, o.cut.r, o.cutAngle, Math.PI - o.cutAngle, true);
  if (o.cornerAngle === null) ctx.lineTo(left, top + r);
  else ctx.arc(left + r, bottom - r, r, Math.PI - o.cornerAngle, Math.PI);
  ctx.arc(left + r, top + r, r, Math.PI, Math.PI * 1.5);
  ctx.closePath();
}

function tracePill(ctx: EyeContext, frame: EyeFrame, box: EyeBox): void {
  const radius = Math.min(box.w, box.h) * 0.45;
  const outline = smileOutline(box, radius, frame.smile);
  if (outline) {
    traceSmilingPill(ctx, box, radius, outline);
    return;
  }
  ctx.beginPath();
  ctx.roundRect(box.cx - box.w / 2, box.cy - box.h / 2, box.w, box.h, radius);
}

function drawPill(ctx: EyeContext, frame: EyeFrame, box: EyeBox, size: number): void {
  const top = box.cy - box.h / 2;
  const gradient = ctx.createLinearGradient(0, top, 0, top + box.h);
  gradient.addColorStop(0, frame.palette.light);
  gradient.addColorStop(0.35, frame.palette.mid);
  gradient.addColorStop(1, frame.palette.deep);

  ctx.save();
  if (frame.openness < 1) clipToLids(ctx, frame, box, size);
  setGlow(ctx, frame, size);
  ctx.fillStyle = gradient;
  tracePill(ctx, frame, box);
  ctx.fill();
  clearGlow(ctx);

  // Highlights: a big soft one at the upper inner corner, a small dot lower outside.
  ctx.fillStyle = withAlpha('#ffffff', 0.92);
  ctx.beginPath();
  ctx.ellipse(box.cx - box.w * 0.18, top + box.h * 0.24, box.w * 0.14, box.h * 0.1, -0.35, 0, TAU);
  ctx.fill();
  ctx.fillStyle = withAlpha('#ffffff', 0.55);
  ctx.beginPath();
  ctx.arc(box.cx + box.w * 0.17, top + box.h * 0.72, box.w * 0.06, 0, TAU);
  ctx.fill();
  ctx.restore();
}

function drawClosedLine(ctx: EyeContext, frame: EyeFrame, box: EyeBox, size: number): void {
  const thickness = size * 0.055;
  ctx.save();
  setGlow(ctx, frame, size);
  ctx.fillStyle = frame.palette.mid;
  ctx.beginPath();
  ctx.roundRect(box.cx - box.w * 0.6, box.cy + box.h * 0.25, box.w * 1.2, thickness, thickness / 2);
  ctx.fill();
  ctx.restore();
}

/** Happy eyes: a glowing upward arc, like "^". */
function drawArc(ctx: EyeContext, frame: EyeFrame, box: EyeBox, size: number): void {
  const y = box.cy + size * 0.12;
  const r = size * 0.2;
  ctx.save();
  ctx.lineCap = 'round';
  setGlow(ctx, frame, size);
  ctx.strokeStyle = frame.palette.mid;
  ctx.lineWidth = size * 0.13;
  ctx.beginPath();
  ctx.arc(box.cx, y, r, Math.PI * 1.1, Math.PI * 1.9);
  ctx.stroke();
  clearGlow(ctx);
  ctx.strokeStyle = withAlpha(frame.palette.light, 0.9);
  ctx.lineWidth = size * 0.04;
  ctx.beginPath();
  ctx.arc(box.cx, y - size * 0.02, r, Math.PI * 1.25, Math.PI * 1.55);
  ctx.stroke();
  ctx.restore();
}

/** Points of the classic parametric heart, x = 16 sin³t, y = 13 cos t − 5 cos 2t − …. */
const HEART_POINTS = 48;
const HEART_HALF_WIDTH = 16; // of the parametric curve
const HEART_MID_Y = -2.5; // vertical centre of the curve (top ≈ 12, tip ≈ -17)

/** Love eyes: a glowing pink heart with a white highlight (eye_images.py draw_heart_eye). */
function drawHeart(ctx: EyeContext, frame: EyeFrame, box: EyeBox, size: number): void {
  const half = box.w * 0.72; // the heart's half width in pixels (≈ w × 0.62 × 1.14 in Python)
  const scale = half / HEART_HALF_WIDTH;
  const top = box.cy - half;
  const gradient = ctx.createLinearGradient(0, top, 0, box.cy + half);
  gradient.addColorStop(0, frame.palette.light);
  gradient.addColorStop(0.35, frame.palette.mid);
  gradient.addColorStop(1, frame.palette.deep);

  ctx.save();
  setGlow(ctx, frame, size);
  ctx.fillStyle = gradient;
  ctx.beginPath();
  for (let i = 0; i < HEART_POINTS; i += 1) {
    const t = (i / HEART_POINTS) * TAU;
    const x = 16 * Math.sin(t) ** 3;
    const y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
    const px = box.cx + x * scale;
    const py = box.cy - (y - HEART_MID_Y) * scale;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.closePath();
  ctx.fill();
  clearGlow(ctx);
  ctx.fillStyle = withAlpha('#ffffff', 0.9);
  ctx.beginPath();
  ctx.ellipse(box.cx - half * 0.37, box.cy - half * 0.45, half * 0.16, half * 0.11, -0.5, 0, TAU);
  ctx.fill();
  ctx.restore();
}

function drawRing(ctx: EyeContext, frame: EyeFrame, size: number): void {
  if (!frame.ring || frame.ring.progress <= 0) return;
  const { progress, radius, alpha, color } = frame.ring;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = size * 0.035;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size * radius, -Math.PI / 2, -Math.PI / 2 + progress * TAU);
  ctx.stroke();
  ctx.restore();
}

function drawOrbitDots(ctx: EyeContext, frame: EyeFrame, box: EyeBox, size: number): void {
  if (!frame.orbitDots) return;
  const { phase, count } = frame.orbitDots;
  const orbit = Math.max(box.w, box.h) * 0.62;
  ctx.save();
  ctx.fillStyle = frame.palette.light;
  for (let i = 0; i < count; i += 1) {
    const angle = phase * TAU + i * 0.5;
    ctx.globalAlpha = 1 - i * 0.25;
    ctx.beginPath();
    ctx.arc(
      box.cx + Math.cos(angle) * orbit,
      box.cy + Math.sin(angle) * orbit,
      size * 0.03,
      0,
      TAU,
    );
    ctx.fill();
  }
  ctx.restore();
}

/** Clear the canvas and paint one eye. `size` is the canvas width = height in pixels. */
export function drawEye(ctx: EyeContext, frame: EyeFrame, size: number): void {
  ctx.clearRect(0, 0, size, size);
  if (frame.shape === 'off') return; // screen off: nothing glows
  const box = eyeBox(frame, size);
  if (frame.shape === 'arc') {
    drawArc(ctx, frame, box, size);
  } else if (frame.shape === 'heart') {
    drawHeart(ctx, frame, box, size);
  } else if (frame.openness < CLOSED_BELOW) {
    drawClosedLine(ctx, frame, box, size);
  } else {
    drawPill(ctx, frame, box, size);
  }
  drawRing(ctx, frame, size);
  drawOrbitDots(ctx, frame, box, size);
}
