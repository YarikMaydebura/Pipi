import { describe, expect, it } from 'vitest';
import { showcaseRequested } from './showcaseMode';
import { centerPosition, parseWindowCommand, showcaseBounds } from './windowMath';

const SIZE = { width: 320, height: 420 };

describe('showcase mode', () => {
  it('is requested with the --showcase flag or PIPI_SHOWCASE=1', () => {
    expect(showcaseRequested(['electron', '.', '--showcase'], {})).toBe(true);
    expect(showcaseRequested(['electron', '.'], { PIPI_SHOWCASE: '1' })).toBe(true);
    expect(showcaseRequested(['electron', '.'], { PIPI_SHOWCASE: '0' })).toBe(false);
    expect(showcaseRequested(['electron', '.'], {})).toBe(false);
  });

  it('centres a window in the work area', () => {
    const workArea = { x: 0, y: 25, width: 1440, height: 800 };

    expect(centerPosition(workArea, SIZE)).toEqual({ x: 560, y: 215 });
  });

  it('doubles the pet on a large screen and keeps it centred', () => {
    const workArea = { x: 0, y: 25, width: 2560, height: 1380 };

    expect(showcaseBounds(workArea, SIZE)).toEqual({ x: 960, y: 295, width: 640, height: 840 });
  });

  it('shrinks the showcase to fit a small screen, keeping the shape', () => {
    const workArea = { x: 0, y: 25, width: 1440, height: 800 };

    const bounds = showcaseBounds(workArea, SIZE);

    expect(bounds.height).toBe(768); // work area minus a margin top and bottom
    expect(bounds.width).toBe(585);
    expect(bounds.y).toBe(41);
    expect(bounds.x).toBe(428);
  });

  it('never makes the showcase smaller than the normal pet', () => {
    const tiny = { x: 0, y: 0, width: 400, height: 300 };

    expect(showcaseBounds(tiny, SIZE)).toMatchObject(SIZE);
  });

  it('accepts a centre command with a clamped duration', () => {
    expect(parseWindowCommand({ action: 'center', durationMs: 900 })).toEqual({
      action: 'center',
      durationMs: 900,
    });
    expect(parseWindowCommand({ action: 'center', durationMs: 99999 })).toEqual({
      action: 'center',
      durationMs: 5000,
    });
    expect(parseWindowCommand({ action: 'center' })).toBeNull();
    expect(parseWindowCommand({ action: 'center', durationMs: Number.NaN })).toBeNull();
  });
});
