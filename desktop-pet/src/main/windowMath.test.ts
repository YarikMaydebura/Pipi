import { describe, expect, it } from 'vitest';
import { DEFAULT_BRAIN_URL, resolveBrainUrl } from './brainUrl';
import { cornerPosition, easeInOutCubic, lerpPoint, parseWindowCommand } from './windowMath';

const WORK_AREA = { x: 0, y: 25, width: 1440, height: 800 };
const SIZE = { width: 320, height: 420 };

describe('window math', () => {
  it('finds the bottom corner on each side', () => {
    expect(cornerPosition(WORK_AREA, SIZE, 'right')).toEqual({ x: 1104, y: 405 });
    expect(cornerPosition(WORK_AREA, SIZE, 'left')).toEqual({ x: 16, y: 405 });
  });

  it('eases in and out and interpolates', () => {
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(0.5)).toBe(0.5);
    expect(easeInOutCubic(1)).toBe(1);
    expect(easeInOutCubic(2)).toBe(1);
    expect(lerpPoint({ x: 0, y: 0 }, { x: 100, y: 50 }, 0.5)).toEqual({ x: 50, y: 25 });
  });

  it('accepts only valid window commands', () => {
    expect(parseWindowCommand({ action: 'hide' })).toEqual({ action: 'hide' });
    expect(parseWindowCommand({ action: 'show', side: 'left' })).toEqual({
      action: 'show',
      side: 'left',
    });
    expect(parseWindowCommand({ action: 'slide', side: 'right', durationMs: 99_999 })).toEqual({
      action: 'slide',
      side: 'right',
      durationMs: 5000,
    });
    expect(parseWindowCommand({ action: 'slide', side: 'right' })).toBeNull();
    expect(parseWindowCommand({ action: 'place', side: 'up' })).toBeNull();
    expect(parseWindowCommand({ action: 'close' })).toBeNull();
    expect(parseWindowCommand('hide')).toBeNull();
  });
});

describe('brain URL', () => {
  it('defaults to the local brain and accepts loopback overrides only', () => {
    expect(resolveBrainUrl(undefined)).toEqual({ url: DEFAULT_BRAIN_URL });
    expect(resolveBrainUrl(' ws://localhost:9000 ')).toEqual({ url: 'ws://localhost:9000' });
    const remote = resolveBrainUrl('ws://192.168.1.5:8765');
    expect(remote.url).toBe(DEFAULT_BRAIN_URL);
    expect(remote.warning).toContain('PIPI_BRAIN_URL');
    expect(resolveBrainUrl('http://127.0.0.1:8765').url).toBe(DEFAULT_BRAIN_URL);
  });
});
