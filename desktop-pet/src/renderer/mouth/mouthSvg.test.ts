import { computeMouthFrame, MOUTH_SHAPES, SMILE, STROKE } from '@pipi/shared/look';
import { describe, expect, it } from 'vitest';
import { mouthSvgPath } from './mouthSvg';

describe('mouthSvgPath (2D fallback)', () => {
  it.each(MOUTH_SHAPES)('builds a path for %s', (shape) => {
    const path = mouthSvgPath(computeMouthFrame(shape), 100);
    expect(path.d).toMatch(/^M[\d.]+ [\d.]+/);
    expect(path.d).not.toContain('NaN');
    if (!path.filled) expect(path.strokeWidth).toBeGreaterThan(0);
  });

  it('fills only the big smile and draws nothing when off', () => {
    const filled = MOUTH_SHAPES.filter((s) => mouthSvgPath(computeMouthFrame(s), 100).filled);
    expect(filled).toEqual(['big_smile']);
    expect(mouthSvgPath(computeMouthFrame('off'), 100).d).toBe('');
  });

  it('uses the same smile geometry as the canvas drawer', () => {
    const path = mouthSvgPath(computeMouthFrame('smile'), 100);
    const startX = SMILE.cx + SMILE.r * Math.cos(SMILE.from);
    expect(path.d.startsWith(`M${Math.round(startX * 10000) / 100} `)).toBe(true);
    expect(path.strokeWidth).toBeCloseTo(STROKE * 2 * 100, 9);
  });
});
