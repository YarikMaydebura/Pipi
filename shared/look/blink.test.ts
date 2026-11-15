import { describe, expect, it } from 'vitest';
import {
  blinkAmount,
  BlinkScheduler,
  BLINK_DURATION_S,
  BLINK_MAX_GAP_S,
  BLINK_MIN_GAP_S,
} from './blink';

describe('blink', () => {
  it('closes and reopens within one blink duration', () => {
    expect(blinkAmount(-0.01)).toBe(0);
    expect(blinkAmount(BLINK_DURATION_S * 0.4)).toBeCloseTo(1);
    expect(blinkAmount(BLINK_DURATION_S + 0.01)).toBe(0);
  });

  it('waits between the minimum and maximum gap', () => {
    for (const r of [0, 0.999]) {
      const blinks = new BlinkScheduler(0, () => r);
      const gap = BLINK_MIN_GAP_S + r * (BLINK_MAX_GAP_S - BLINK_MIN_GAP_S);
      expect(blinks.update(gap - 0.01)).toBe(0);
      blinks.update(gap);
      expect(blinks.update(gap + 0.05)).toBeGreaterThan(0);
    }
  });
});
