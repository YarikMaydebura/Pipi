import { describe, expect, it } from 'vitest';
import { EYE_PRESETS, SMILING_EYES } from './eyeFrame';
import { smileCut, smileOutline, type EyeRect } from './smileOutline';

const SIZE = 512;
const eyeRect = (w: number, h: number): EyeRect => ({
  cx: SIZE / 2,
  cy: SIZE / 2,
  w: w * SIZE,
  h: h * SIZE,
});
const IDLE = eyeRect(0.4, 0.6);
const cornerRadius = (eye: EyeRect): number => Math.min(eye.w, eye.h) * 0.45;

describe('smile outline (port of eye_images.py smile_mask)', () => {
  it('uses the same depth as the Blender eye images for the resting states', () => {
    expect(SMILING_EYES).toBe(0.22);
    expect(EYE_PRESETS.idle.smile).toBe(SMILING_EYES);
    expect(EYE_PRESETS.listening.smile).toBe(SMILING_EYES);
    expect(EYE_PRESETS.surprised.smile).toBe(0);
  });

  it('cuts a circle whose top sits `smile * h` above the bottom edge', () => {
    const cut = smileCut(IDLE, SMILING_EYES);
    const bottom = IDLE.cy + IDLE.h / 2;
    expect(cut.cy - cut.r).toBeCloseTo(bottom - SMILING_EYES * IDLE.h, 6);
    expect(cut.cx).toBe(IDLE.cx);
    // Python: radius = (w²/4 + depth²) / (2 depth) * 1.15  →  ≈128.1 px at 512 px.
    expect(cut.r).toBeCloseTo(128.07, 1);
  });

  it('meets the eye on its rounded bottom corner, on both circles', () => {
    const r = cornerRadius(IDLE);
    const outline = smileOutline(IDLE, r, SMILING_EYES);
    expect(outline).not.toBeNull();
    if (!outline) return;
    const { cut, meet, cornerAngle } = outline;
    expect(cornerAngle).not.toBeNull();
    expect(cornerAngle ?? -1).toBeGreaterThanOrEqual(0);
    expect(cornerAngle ?? 9).toBeLessThanOrEqual(Math.PI / 2);
    const corner = { x: IDLE.cx + IDLE.w / 2 - r, y: IDLE.cy + IDLE.h / 2 - r };
    expect(Math.hypot(meet.x - corner.x, meet.y - corner.y)).toBeCloseTo(r, 6);
    expect(Math.hypot(meet.x - cut.cx, meet.y - cut.cy)).toBeCloseTo(cut.r, 6);
    // The meeting point is above the cut's centre: the curve bulges upward.
    expect(outline.cutAngle).toBeLessThan(0);
    expect(outline.cutAngle).toBeGreaterThan(-Math.PI / 2);
  });

  it('meets the straight side when the corners are small', () => {
    const outline = smileOutline(IDLE, 4, SMILING_EYES);
    expect(outline?.cornerAngle).toBeNull();
    expect(outline?.meet.x).toBeCloseTo(IDLE.cx + IDLE.w / 2, 6);
  });

  it('works for the taller listening eye and a speech-stretched eye', () => {
    for (const eye of [eyeRect(0.42, 0.66), eyeRect(0.4, 0.6 * 1.06)]) {
      expect(smileOutline(eye, cornerRadius(eye), SMILING_EYES)).not.toBeNull();
    }
  });

  it('returns null when the eye does not smile', () => {
    expect(smileOutline(IDLE, cornerRadius(IDLE), 0)).toBeNull();
    expect(smileOutline(eyeRect(0, 0.6), 0, SMILING_EYES)).toBeNull();
  });
});
