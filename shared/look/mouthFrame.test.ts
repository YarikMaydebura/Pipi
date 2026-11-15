import { EyeState } from '../protocol';
import { describe, expect, it } from 'vitest';
import {
  computeMouthFrame,
  MOUTH_FOR_STATE,
  mouthForState,
  sameMouthFrame,
  TALK_MIN_LEVEL,
} from './mouthFrame';
import { isMouthShape, MOUTH_SHAPES, wavyPoints } from './mouthShapes';
import { PET_EYE_LOOKS } from './eyeFrame';

describe('mouthForState', () => {
  it('has a mouth for every protocol eye state and pet-only look', () => {
    expect(Object.keys(MOUTH_FOR_STATE).sort()).toEqual(
      [...EyeState.options, ...PET_EYE_LOOKS].sort(),
    );
    expect(mouthForState('love')).toBe('big_smile');
  });

  it('smiles by default and never looks neutral or sad at rest', () => {
    expect(mouthForState('idle')).toBe('smile');
    expect(mouthForState('listening')).toBe('smile');
    expect(mouthForState('determined')).toBe('smile');
    expect(mouthForState('sad')).toBe('wavy');
  });

  it('matches the expressions', () => {
    expect(mouthForState('happy')).toBe('big_smile');
    expect(mouthForState('surprised')).toBe('small_o');
    expect(mouthForState('thinking')).toBe('small_o');
    expect(mouthForState('sleepy')).toBe('flat');
    expect(mouthForState('off')).toBe('off');
  });
});

describe('computeMouthFrame', () => {
  it('shows the resting shape at full size while silent', () => {
    for (const shape of MOUTH_SHAPES) {
      expect(computeMouthFrame(shape)).toMatchObject({ shape, open: 1 });
    }
  });

  it('turns the screen off with the eyes', () => {
    expect(computeMouthFrame('off', 0.8)).toEqual({ shape: 'off', open: 0, glow: 0 });
  });

  it('opens the smile with the voice, louder = wider, but subtly', () => {
    const quiet = computeMouthFrame('smile', 0.2);
    const loud = computeMouthFrame('smile', 1);
    expect(quiet.shape).toBe('big_smile');
    expect(loud.shape).toBe('big_smile');
    expect(loud.open).toBeGreaterThan(quiet.open);
    expect(loud.open).toBeLessThan(1); // never wider than the happy big smile
  });

  it('closes back to the smile in pauses between words', () => {
    expect(computeMouthFrame('smile', TALK_MIN_LEVEL / 2).shape).toBe('smile');
  });

  it('keeps flat and wavy shapes while talking, and grows the "o" a little', () => {
    expect(computeMouthFrame('flat', 0.9).shape).toBe('flat');
    expect(computeMouthFrame('wavy', 0.9).shape).toBe('wavy');
    expect(computeMouthFrame('small_o', 1).open).toBeGreaterThan(1);
  });

  it('keeps every value in range', () => {
    for (const shape of MOUTH_SHAPES) {
      for (const level of [-1, 0, 0.5, 1, 3]) {
        const frame = computeMouthFrame(shape, level);
        expect(frame.glow).toBeGreaterThanOrEqual(0);
        expect(frame.glow).toBeLessThanOrEqual(1);
        expect(frame.open).toBeGreaterThan(0);
        expect(frame.open).toBeLessThanOrEqual(1.25);
      }
    }
  });

  it('compares frames for redraw skipping', () => {
    const a = computeMouthFrame('smile');
    expect(sameMouthFrame(null, a)).toBe(false);
    expect(sameMouthFrame(a, computeMouthFrame('smile'))).toBe(true);
    expect(sameMouthFrame(a, computeMouthFrame('smile', 0.5))).toBe(false);
  });
});

describe('mouth shapes', () => {
  it('recognises shape names', () => {
    expect(isMouthShape('small_o')).toBe(true);
    expect(isMouthShape('frown')).toBe(false);
  });

  it('samples the wavy line across the middle of the image', () => {
    const points = wavyPoints(512);
    expect(points).toHaveLength(64);
    expect(points[0]?.x).toBeCloseTo(512 * 0.26, 6);
    expect(points.at(-1)?.x).toBeCloseTo(512 * 0.74, 6);
    for (const p of points) expect(Math.abs(p.y - 256)).toBeLessThanOrEqual(512 * 0.045 + 1e-9);
  });
});
