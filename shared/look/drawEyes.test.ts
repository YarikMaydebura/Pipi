import { EyeState } from '../protocol';
import { describe, expect, it } from 'vitest';
import { canvasRecorder } from '../testing/canvasRecorder';
import { drawEye, withAlpha, type EyeContext } from './drawEyes';
import { computeEyeFrame, PALETTES } from './eyeFrame';

const SIZE = 512;
const recorder = () => canvasRecorder<EyeContext>();

describe('drawEye', () => {
  it.each(EyeState.options)('draws %s without errors and clears first', (state) => {
    const { ctx, calls } = recorder();
    drawEye(ctx, computeEyeFrame(state, 0.5), SIZE);
    expect(calls[0]).toEqual({ name: 'clearRect', args: [0, 0, SIZE, SIZE] });
    const saves = calls.filter((c) => c.name === 'save').length;
    const restores = calls.filter((c) => c.name === 'restore').length;
    expect(saves).toBe(restores);
  });

  it('draws nothing but a clear for the off state', () => {
    const { ctx, calls } = recorder();
    drawEye(ctx, computeEyeFrame('off', 0), SIZE);
    expect(calls.map((c) => c.name)).toEqual(['clearRect']);
  });

  it('draws a non-smiling open eye as a teal rounded rectangle', () => {
    const { ctx, calls, colors } = recorder();
    drawEye(ctx, computeEyeFrame('surprised', 0), SIZE);
    expect(calls.some((c) => c.name === 'roundRect')).toBe(true);
    expect(colors.has(PALETTES.teal.mid)).toBe(true);
  });

  it.each(['idle', 'listening'] as const)(
    'draws %s eyes smiling: the bottom is an upward arc, not a rounded rectangle',
    (state) => {
      const { ctx, calls, colors } = recorder();
      drawEye(ctx, computeEyeFrame(state, 0), SIZE);
      expect(calls.some((c) => c.name === 'roundRect')).toBe(false);
      // The cut circle is traced anticlockwise (over its top) from right to left.
      const cut = calls.find((c) => c.name === 'arc' && c.args[5] === true);
      expect(cut).toBeDefined();
      expect(Number(cut?.args[1])).toBeGreaterThan(SIZE / 2); // its centre is below the eye
      expect(colors.has(PALETTES.teal.mid)).toBe(true);
    },
  );

  it('keeps the smile while blinking, until the eye is a closed line', () => {
    const half = recorder();
    drawEye(half.ctx, computeEyeFrame('idle', 0, { blink: 0.5 }), SIZE);
    expect(half.calls.some((c) => c.name === 'clip')).toBe(true);
    expect(half.calls.some((c) => c.name === 'arc' && c.args[5] === true)).toBe(true);
    const closed = recorder();
    drawEye(closed.ctx, computeEyeFrame('idle', 0, { blink: 1 }), SIZE);
    expect(closed.calls.some((c) => c.name === 'arc')).toBe(false);
    expect(closed.calls.some((c) => c.name === 'roundRect')).toBe(true);
  });

  it('draws happy eyes as an arc, not a rectangle', () => {
    const { ctx, calls } = recorder();
    drawEye(ctx, computeEyeFrame('happy', 0), SIZE);
    expect(calls.some((c) => c.name === 'roundRect')).toBe(false);
    expect(calls.some((c) => c.name === 'stroke')).toBe(true);
  });

  it('draws love eyes as a pink heart outline with a highlight', () => {
    const { ctx, calls, colors } = recorder();
    drawEye(ctx, computeEyeFrame('love', 0), SIZE);
    expect(calls.filter((c) => c.name === 'lineTo').length).toBeGreaterThan(20);
    expect(calls.some((c) => c.name === 'roundRect')).toBe(false);
    expect(calls.some((c) => c.name === 'ellipse')).toBe(true);
    expect(colors.has(PALETTES.heartPink.mid)).toBe(true);
    expect(colors.has(PALETTES.teal.mid)).toBe(false);
  });

  it('clips with the eyelids when the eye is partly closed', () => {
    const open = recorder();
    drawEye(open.ctx, computeEyeFrame('idle', 0), SIZE);
    expect(open.calls.some((c) => c.name === 'clip')).toBe(false);
    const sleepy = recorder();
    drawEye(sleepy.ctx, computeEyeFrame('sleepy', 0), SIZE);
    expect(sleepy.calls.some((c) => c.name === 'clip')).toBe(true);
  });

  it('uses the state colours for countdown and the go signal', () => {
    const countdown = recorder();
    drawEye(countdown.ctx, computeEyeFrame('countdown', 0.2), SIZE);
    expect(countdown.colors.has(PALETTES.amber.mid)).toBe(true);
    const go = recorder();
    drawEye(go.ctx, computeEyeFrame('signal_go', 0.2), SIZE);
    expect(go.colors.has(PALETTES.green.mid)).toBe(true);
  });

  it('moves the eye with the gaze', () => {
    const roundRectX = (gazeX: number): number => {
      const { ctx, calls } = recorder();
      drawEye(ctx, computeEyeFrame('surprised', 0, { gaze: { x: gazeX, y: 0 } }), SIZE);
      return Number(calls.find((c) => c.name === 'roundRect')?.args[0]);
    };
    expect(roundRectX(1)).toBeGreaterThan(roundRectX(0));
    expect(roundRectX(-1)).toBeLessThan(roundRectX(0));
  });

  it('moves the smiling eye with the gaze too', () => {
    const startX = (gazeX: number): number => {
      const { ctx, calls } = recorder();
      drawEye(ctx, computeEyeFrame('idle', 0, { gaze: { x: gazeX, y: 0 } }), SIZE);
      return Number(calls.find((c) => c.name === 'moveTo')?.args[0]);
    };
    expect(startX(1)).toBeGreaterThan(startX(0));
    expect(startX(-1)).toBeLessThan(startX(0));
  });
});

describe('withAlpha', () => {
  it('converts hex colours to rgba and clamps alpha', () => {
    expect(withAlpha('#3fe0c5', 0.5)).toBe('rgba(63,224,197,0.5)');
    expect(withAlpha('#ffffff', 2)).toBe('rgba(255,255,255,1)');
  });
});
