import { describe, expect, it } from 'vitest';
import {
  baseFadeSeconds,
  isLoopClip,
  loopGestureSeconds,
  planMotion,
  ROBOT_CLIPS,
  SLEEP_FADE_S,
} from './motionPlan';
import {
  PROCEDURAL_MOTIONS,
  PROCEDURAL_NAMES,
  REST,
  addPoses,
  sampleMotion,
  scalePose,
} from './proceduralMotions';

const ALL = (clip: string): boolean => ROBOT_CLIPS.includes(clip);
const NONE = (): boolean => false;
const DIALOGUE_GESTURES = [
  'nod',
  'shake_head',
  'think',
  'excited',
  'celebrate',
  'shrug',
  'wave',
  'signature_wave',
];

describe('planMotion', () => {
  it('uses the clip of the same name when the model has it', () => {
    expect(planMotion('nod', ALL)).toEqual({ kind: 'clip', clip: 'nod', loop: false });
    expect(planMotion('dance', ALL)).toEqual({ kind: 'clip', clip: 'dance', loop: true });
  });

  it('maps gesture names onto the robot clips', () => {
    expect(planMotion('wave', ALL)).toMatchObject({ clip: 'signature_wave' });
    expect(planMotion('excited', ALL)).toMatchObject({ clip: 'happy' });
    expect(planMotion('jump_in', ALL)).toMatchObject({ clip: 'wake_up' });
  });

  it('falls back to the next candidate clip, then to a procedural motion', () => {
    expect(planMotion('celebrate', (c) => c === 'happy')).toMatchObject({ clip: 'happy' });
    expect(planMotion('shrug', ALL)).toEqual({ kind: 'procedural', name: 'shrug' });
    expect(planMotion('wave', NONE)).toEqual({ kind: 'procedural', name: 'signature_wave' });
  });

  it('can show every dialogue gesture and every glb clip, even without clips', () => {
    for (const name of [...DIALOGUE_GESTURES, ...ROBOT_CLIPS]) {
      expect(planMotion(name, NONE).kind, name).toBe('procedural');
      expect(planMotion(name, ALL).kind, name).not.toBe('unknown');
    }
  });

  it('reports unknown motions', () => {
    expect(planMotion('moonwalk', ALL)).toEqual({ kind: 'unknown', name: 'moonwalk' });
  });

  it('knows loops, gesture lengths and fades', () => {
    expect(isLoopClip('sleep')).toBe(true);
    expect(isLoopClip('wake_up')).toBe(false);
    expect(loopGestureSeconds('dance')).toBeGreaterThan(loopGestureSeconds('think'));
    expect(baseFadeSeconds('sleep')).toBe(SLEEP_FADE_S);
    expect(baseFadeSeconds('idle')).toBeLessThan(SLEEP_FADE_S);
  });
});

describe('procedural motions', () => {
  const oneShots = PROCEDURAL_NAMES.filter((n) => !PROCEDURAL_MOTIONS[n]?.loop);
  const loops = PROCEDURAL_NAMES.filter((n) => PROCEDURAL_MOTIONS[n]?.loop);

  it.each(oneShots.filter((n) => n !== 'wake_up'))('%s starts and ends at rest', (name) => {
    const def = PROCEDURAL_MOTIONS[name];
    if (!def) throw new Error(name);
    for (const p of [0, 1]) {
      for (const value of Object.values(def.sample(p))) expect(Math.abs(value)).toBeLessThan(1e-6);
    }
  });

  it('wake_up starts in the sleep slump and ends at rest', () => {
    const sleep = sampleMotion('sleep', 0);
    const start = sampleMotion('wake_up', 0);
    expect(start.headPitch).toBeCloseTo(sleep.headPitch, 2);
    expect(start.bodyBow).toBeCloseTo(sleep.bodyBow, 2);
    for (const value of Object.values(sampleMotion('wake_up', 99))) {
      expect(Math.abs(value)).toBeLessThan(1e-6);
    }
  });

  it.each(loops)('%s loops seamlessly', (name) => {
    const def = PROCEDURAL_MOTIONS[name];
    if (!def) throw new Error(name);
    const a = def.sample(0);
    const b = def.sample(1);
    for (const key of Object.keys(a) as (keyof typeof a)[]) expect(a[key]).toBeCloseTo(b[key], 6);
  });

  it('samples by time, wrapping loops and clamping one-shots', () => {
    expect(sampleMotion('nod', 100)).toEqual(sampleMotion('nod', 1.1));
    expect(sampleMotion('moonwalk', 1)).toEqual(REST);
    const dance = PROCEDURAL_MOTIONS['dance'];
    if (!dance) throw new Error('dance');
    expect(sampleMotion('dance', dance.durationS * 2.25).bodyLean).toBeCloseTo(
      sampleMotion('dance', dance.durationS * 0.25).bodyLean,
      6,
    );
  });

  it('adds and scales poses', () => {
    const p = addPoses(REST, scalePose({ ...REST, headYaw: 1 }, 0.3));
    expect(p.headYaw).toBeCloseTo(0.3);
  });
});
