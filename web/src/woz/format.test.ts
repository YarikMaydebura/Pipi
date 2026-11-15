import { describe, expect, it } from 'vitest';
import {
  formatClock,
  formatMs,
  humanize,
  isSlowTurn,
  reconnectDelayMs,
  remainingSeconds,
  timerProgress,
} from './format';

describe('formatClock', () => {
  it('formats minutes and seconds', () => {
    expect(formatClock(240)).toBe('4:00');
    expect(formatClock(65)).toBe('1:05');
    expect(formatClock(4.2)).toBe('0:05'); // rounds up: never shows 0:00 while time is left
  });

  it('formats hours and clamps bad values', () => {
    expect(formatClock(3725)).toBe('1:02:05');
    expect(formatClock(-3)).toBe('0:00');
    expect(formatClock(Number.NaN)).toBe('0:00');
  });
});

describe('remainingSeconds', () => {
  const timer = { remaining_s: 100, total_s: 240 };

  it('counts down locally since the last update', () => {
    expect(remainingSeconds(timer, 1_000, 11_000, false)).toBe(90);
  });

  it('stops at zero and freezes while paused', () => {
    expect(remainingSeconds(timer, 0, 500_000, false)).toBe(0);
    expect(remainingSeconds(timer, 0, 50_000, true)).toBe(100);
  });

  it('ignores a local clock that runs backwards', () => {
    expect(remainingSeconds(timer, 5_000, 1_000, false)).toBe(100);
  });
});

describe('small helpers', () => {
  it('computes timer progress safely', () => {
    expect(timerProgress(60, 240)).toBeCloseTo(0.75);
    expect(timerProgress(10, 0)).toBe(0);
    expect(timerProgress(500, 240)).toBe(0);
  });

  it('formats latencies and flags slow turns', () => {
    expect(formatMs(850)).toBe('850 ms');
    expect(formatMs(1234)).toBe('1.2 s');
    expect(formatMs(null)).toBe('–');
    expect(isSlowTurn(2600)).toBe(true);
    expect(isSlowTurn(2500)).toBe(false);
    expect(isSlowTurn(undefined)).toBe(false);
  });

  it('backs off exponentially up to 10 s', () => {
    expect([0, 1, 2, 3, 4, 5, 50].map(reconnectDelayMs)).toEqual([
      500, 1000, 2000, 4000, 8000, 10_000, 10_000,
    ]);
  });

  it('humanizes identifiers', () => {
    expect(humanize('desktop_pet')).toBe('Desktop pet');
    expect(humanize('GAME_CROCODILE')).toBe('Game crocodile');
  });
});
