import { EyeState } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import {
  canAutoBlink,
  computeEyeFrame,
  EYE_PRESETS,
  mirrorForRightEye,
  PALETTES,
  PET_EYE_LOOKS,
} from './eyeFrame';

const ALL_STATES = [...EyeState.options, ...PET_EYE_LOOKS];

describe('computeEyeFrame', () => {
  it('has a preset for every protocol eye state and every pet-only look', () => {
    expect(Object.keys(EYE_PRESETS).sort()).toEqual([...ALL_STATES].sort());
  });

  it.each(ALL_STATES)('returns finite, in-range values for %s', (state) => {
    for (const t of [0, 0.37, 1.5, 12.3]) {
      const frame = computeEyeFrame(state, t, { gaze: { x: 0.3, y: -0.2 }, blink: 0.4 });
      expect(frame.state).toBe(state);
      expect(frame.openness).toBeGreaterThanOrEqual(0);
      expect(frame.openness).toBeLessThanOrEqual(1);
      expect(frame.glow).toBeGreaterThanOrEqual(0);
      expect(frame.glow).toBeLessThanOrEqual(1);
      for (const value of [frame.width, frame.height, frame.gazeX, frame.gazeY, frame.lidTilt]) {
        expect(Number.isFinite(value)).toBe(true);
      }
      if (frame.ring) {
        expect(frame.ring.progress).toBeGreaterThanOrEqual(0);
        expect(frame.ring.progress).toBeLessThanOrEqual(1);
      }
    }
  });

  it('gives every state a visibly different look', () => {
    const looks = ALL_STATES.map((state) => {
      const frame = computeEyeFrame(state, 0.3);
      return JSON.stringify({ ...frame, state: null });
    });
    expect(new Set(looks).size).toBe(ALL_STATES.length);
  });

  it('is deterministic for equal inputs', () => {
    expect(computeEyeFrame('listening', 2.1)).toEqual(computeEyeFrame('listening', 2.1));
  });

  it('draws blink as fully closed and off as a dark screen', () => {
    expect(computeEyeFrame('blink', 0).openness).toBe(0);
    expect(computeEyeFrame('off', 0).shape).toBe('off');
    expect(computeEyeFrame('off', 0).glow).toBe(0);
    expect(computeEyeFrame('happy', 0).shape).toBe('arc');
  });

  it('closes blinkable eyes with the blink amount but ignores it for non-blinking states', () => {
    expect(computeEyeFrame('idle', 0, { blink: 1 }).openness).toBe(0);
    expect(computeEyeFrame('idle', 0, { blink: 0.5 }).openness).toBeCloseTo(0.5);
    expect(computeEyeFrame('countdown', 0, { blink: 1 }).openness).toBe(1);
    expect(canAutoBlink('idle')).toBe(true);
    expect(canAutoBlink('off')).toBe(false);
  });

  it('follows the requested gaze (clamped) unless the state has its own gaze', () => {
    const idle = computeEyeFrame('idle', 0, { gaze: { x: 5, y: -5 } });
    expect(idle.gazeX).toBe(1);
    expect(idle.gazeY).toBe(-1);
    const thinking = computeEyeFrame('thinking', 0, { gaze: { x: -1, y: 1 } });
    expect(thinking.gazeY).toBeLessThan(0); // thinking always looks up
  });

  it('drains the countdown ring once per second', () => {
    const early = computeEyeFrame('countdown', 3.1).ring?.progress ?? 0;
    const late = computeEyeFrame('countdown', 3.9).ring?.progress ?? 0;
    expect(early).toBeGreaterThan(late);
  });

  it('mirrors only the horizontal gaze for the right eye', () => {
    const frame = computeEyeFrame('idle', 0, { gaze: { x: 0.6, y: 0.2 } });
    const right = mirrorForRightEye(frame);
    expect(right.gazeX).toBeCloseTo(-0.6);
    expect(right.gazeY).toBeCloseTo(0.2);
    expect(right.lidTilt).toBe(frame.lidTilt);
  });
});

describe('love eyes (pet-only)', () => {
  it('are pink hearts that never blink', () => {
    const frame = computeEyeFrame('love', 0, { blink: 1 });
    expect(frame.shape).toBe('heart');
    expect(frame.palette).toEqual(PALETTES.heartPink);
    expect(frame.palette.mid).toBe('#ff7a93');
    expect(frame.openness).toBe(1);
    expect(canAutoBlink('love')).toBe(false);
  });

  it('beat gently (the heart grows and shrinks a little)', () => {
    const sizes = [0, 0.2, 0.4, 0.6].map((t) => computeEyeFrame('love', t).width);
    expect(Math.max(...sizes) - Math.min(...sizes)).toBeGreaterThan(0.01);
    for (const w of sizes) expect(Math.abs(w - EYE_PRESETS.love.width)).toBeLessThan(0.05);
  });
});
