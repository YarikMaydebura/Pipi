import { describe, expect, it } from 'vitest';
import { PALETTES } from './eyeFrame';
import { callNames, canvasRecorder } from '../testing/canvasRecorder';
import { drawMouth, type MouthContext } from './drawMouth';
import { computeMouthFrame } from './mouthFrame';
import { MOUTH_SHAPES, SMALL_O, SMILE, STROKE, type MouthShape } from './mouthShapes';

const SIZE = 256;
const recorder = () => canvasRecorder<MouthContext>();

function draw(shape: MouthShape | 'off', level = 0) {
  const rec = recorder();
  drawMouth(rec.ctx, computeMouthFrame(shape, level), SIZE);
  return rec;
}

describe('drawMouth', () => {
  it.each(MOUTH_SHAPES)('draws %s in teal with a glow, clearing first', (shape) => {
    const { calls, colors, state } = draw(shape);
    expect(calls[0]).toEqual({ name: 'clearRect', args: [0, 0, SIZE, SIZE] });
    expect(colors.has(PALETTES.teal.mid)).toBe(true);
    expect(Number(state['shadowBlur'])).toBeGreaterThan(0);
    const names = callNames(calls);
    expect(names.filter((n) => n === 'save')).toHaveLength(
      names.filter((n) => n === 'restore').length,
    );
  });

  it('draws nothing but a clear when the screen is off', () => {
    expect(callNames(draw('off').calls)).toEqual(['clearRect']);
  });

  it('draws the smile as a stroked arc through the bottom of its circle', () => {
    const { calls, state } = draw('smile');
    const arc = calls.find((c) => c.name === 'arc');
    expect(arc?.args).toEqual([
      SMILE.cx * SIZE,
      SMILE.cy * SIZE,
      SMILE.r * SIZE,
      SMILE.from,
      SMILE.to,
    ]);
    expect(state['lineWidth']).toBe(STROKE * 2 * SIZE);
    expect(state['lineCap']).toBe('round');
    expect(callNames(calls)).toContain('stroke');
  });

  it('draws the big smile as a filled lower half-ellipse', () => {
    const { calls } = draw('big_smile');
    const ellipse = calls.find((c) => c.name === 'ellipse');
    expect(ellipse?.args.slice(5)).toEqual([0, Math.PI]);
    expect(callNames(calls)).toContain('fill');
    expect(callNames(calls)).not.toContain('stroke');
  });

  it('opens the mouth with the speech level', () => {
    const depth = (level: number): number =>
      Number(draw('smile', level).calls.find((c) => c.name === 'ellipse')?.args[3]);
    expect(depth(0.9)).toBeGreaterThan(depth(0.2));
  });

  it('draws the "o" as a full ring and the sleepy mouth as a rounded bar', () => {
    const ring = draw('small_o').calls.find((c) => c.name === 'arc');
    expect(ring?.args[2]).toBe(SMALL_O.r * SIZE);
    expect(ring?.args[4]).toBeCloseTo(Math.PI * 2, 9);
    expect(callNames(draw('flat').calls)).toContain('roundRect');
  });

  it('draws the wavy mouth as one connected line', () => {
    const names = callNames(draw('wavy').calls);
    expect(names.filter((n) => n === 'moveTo')).toHaveLength(1);
    expect(names.filter((n) => n === 'lineTo')).toHaveLength(63);
  });
});
