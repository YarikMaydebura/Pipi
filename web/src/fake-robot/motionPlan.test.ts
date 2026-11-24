import { describe, expect, it } from 'vitest';
import { ACT_MOTION_NAMES, RPS_CHOICE_MOTION_NAMES, STARE_RPS_MOTION_NAMES } from './gameMotions';
import {
  baseFadeSeconds,
  HELD_MAX_S,
  HELD_MOTIONS,
  isLoopClip,
  LOOP_CLIPS,
  loopGestureSeconds,
  motionMode,
  motionSeconds,
  ONE_SHOT_CLIPS,
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
  type RobotPose,
} from './proceduralMotions';
import { mixPoses, pulse, throughKeys } from './robotPose';

function sampleFor(name: string, p: number): RobotPose {
  const def = PROCEDURAL_MOTIONS[name];
  if (!def) throw new Error(`no procedural motion ${name}`);
  return def.sample(p);
}

const ALL = (clip: string): boolean => ROBOT_CLIPS.includes(clip);
const NONE = (): boolean => false;
/** The clips alpha_mini.glb had before the game clips were exported. */
const OLD_GLB_CLIPS = [
  'idle',
  'talk',
  'think',
  'sleep',
  'listen',
  'dance',
  'signature_wave',
  'nod',
  'shake_head',
  'happy',
  'celebrate',
  'wake_up',
];
const GAME_MOTION_NAMES = [
  ...ACT_MOTION_NAMES,
  'duel_ready',
  'duel_draw',
  'duel_hit',
  'duel_win',
  'sad',
  'shrug',
  'bow',
];
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
    expect(planMotion('nod', ALL)).toEqual({ kind: 'clip', clip: 'nod', mode: 'once' });
    expect(planMotion('dance', ALL)).toEqual({ kind: 'clip', clip: 'dance', mode: 'timed' });
  });

  it('maps gesture names onto the robot clips', () => {
    expect(planMotion('wave', ALL)).toMatchObject({ clip: 'signature_wave' });
    expect(planMotion('excited', ALL)).toMatchObject({ clip: 'happy' });
    expect(planMotion('jump_in', ALL)).toMatchObject({ clip: 'wake_up' });
  });

  it('falls back to the next candidate clip, then to a procedural motion', () => {
    expect(planMotion('celebrate', (c) => c === 'happy')).toMatchObject({ clip: 'happy' });
    expect(planMotion('excited', NONE)).toEqual({
      kind: 'procedural',
      name: 'happy',
      mode: 'once',
    });
    expect(planMotion('wave', NONE)).toEqual({
      kind: 'procedural',
      name: 'signature_wave',
      mode: 'once',
    });
  });

  it('can show every dialogue gesture and every glb clip, even without clips', () => {
    for (const name of [...DIALOGUE_GESTURES, ...ROBOT_CLIPS]) {
      expect(planMotion(name, NONE).kind, name).toBe('procedural');
      expect(planMotion(name, ALL).kind, name).not.toBe('unknown');
    }
  });

  it('reports unknown motions', () => {
    expect(planMotion('moonwalk', ALL)).toEqual({ kind: 'unknown', name: 'moonwalk' });
    expect(planMotion('moonwalk', NONE)).toEqual({ kind: 'unknown', name: 'moonwalk' });
    // names that exist on every JavaScript object must not count as motions
    for (const name of ['constructor', 'tostring', 'toString', '__proto__', 'valueof']) {
      expect(planMotion(name, NONE).kind, name).toBe('unknown');
    }
  });

  it('plays the glb clip of a game motion when the model has it', () => {
    for (const name of GAME_MOTION_NAMES) {
      expect(planMotion(name, ALL), name).toMatchObject({ kind: 'clip', clip: name });
    }
  });

  it('falls back to a procedural motion for every game motion the glb lacks', () => {
    const oldGlb = (clip: string): boolean => OLD_GLB_CLIPS.includes(clip);
    for (const name of GAME_MOTION_NAMES) {
      expect(planMotion(name, oldGlb), name).toMatchObject({ kind: 'procedural', name });
      expect(planMotion(name, NONE), name).toMatchObject({ kind: 'procedural', name });
    }
  });

  it('acting loops, stances and rps choices are held; the other game motions play once', () => {
    const held = [...ACT_MOTION_NAMES, 'duel_ready', 'stare_ready', ...RPS_CHOICE_MOTION_NAMES];
    const once = ['duel_draw', 'duel_hit', 'duel_win', 'sad', 'shrug', 'bow'];
    for (const hasClip of [ALL, NONE]) {
      for (const name of held) {
        expect(planMotion(name, hasClip), name).toMatchObject({ mode: 'held' });
      }
      for (const name of [...once, 'stare_lose', 'rps_shake']) {
        expect(planMotion(name, hasClip), name).toMatchObject({ mode: 'once' });
      }
      expect(planMotion('think', hasClip)).toMatchObject({ mode: 'timed' });
    }
  });

  it('keeps every held motion a loop clip, and no clip in both lists', () => {
    expect(HELD_MOTIONS).toHaveLength(13); // 8 act_*, duel_ready, stare_ready, 3 rps choices
    for (const name of HELD_MOTIONS) expect(isLoopClip(name), name).toBe(true);
    for (const name of ONE_SHOT_CLIPS) expect(LOOP_CLIPS, name).not.toContain(name);
    expect(new Set(ROBOT_CLIPS).size).toBe(ROBOT_CLIPS.length);
    expect(ROBOT_CLIPS).toHaveLength(27); // 12 from M2 + 15 game clips
    // staring / rps motions are procedural only: the glb is not expected to have them
    for (const name of STARE_RPS_MOTION_NAMES) expect(ROBOT_CLIPS, name).not.toContain(name);
  });

  it('caps held motions far beyond a crocodile round, and times resting loops', () => {
    expect(motionMode('act_bird')).toBe('held');
    expect(motionSeconds('act_bird', 'held')).toBe(HELD_MAX_S);
    expect(HELD_MAX_S).toBeGreaterThan(60);
    expect(motionSeconds('think', 'timed')).toBe(loopGestureSeconds('think'));
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

  it.each(PROCEDURAL_NAMES)('%s stays within what the joints can do', (name) => {
    const def = PROCEDURAL_MOTIONS[name];
    if (!def) throw new Error(name);
    expect(def.durationS).toBeGreaterThan(0);
    for (let i = 0; i <= 200; i += 1) {
      const sample = def.sample(i / 200);
      for (const [key, value] of Object.entries(sample)) {
        expect(Number.isFinite(value), `${name}.${key}`).toBe(true);
        expect(Math.abs(value), `${name}.${key}`).toBeLessThanOrEqual(Math.PI);
      }
      expect(sample.elbowLBend, `${name} left elbow`).toBeGreaterThanOrEqual(-1e-9);
      expect(sample.elbowRBend, `${name} right elbow`).toBeGreaterThanOrEqual(-1e-9);
      expect(Math.abs(sample.bodyLift), `${name} lift`).toBeLessThan(0.1);
    }
  });
});

/** Largest change of each pose field between two neighbouring samples of a motion. */
function range(name: string, key: keyof RobotPose): number {
  const def = PROCEDURAL_MOTIONS[name];
  if (!def) throw new Error(name);
  const values = Array.from({ length: 101 }, (_, i) => def.sample(i / 100)[key]);
  return Math.max(...values) - Math.min(...values);
}

describe('game motions (procedural fallbacks)', () => {
  it('act_bird flaps both arms together, sideways', () => {
    const bird = PROCEDURAL_MOTIONS['act_bird'];
    if (!bird) throw new Error('act_bird');
    expect(range('act_bird', 'armLRaise')).toBeGreaterThan(1.2);
    for (const p of [0.1, 0.3, 0.6, 0.9]) {
      expect(bird.sample(p).armLRaise).toBeCloseTo(bird.sample(p).armRRaise, 6);
    }
  });

  it('act_boxer throws alternating straight punches from a guard', () => {
    const left = sampleFor('act_boxer', 0.25);
    const right = sampleFor('act_boxer', 0.75);
    const guard = sampleFor('act_boxer', 0);
    expect(guard.elbowLBend).toBeGreaterThan(1.5); // fists up
    expect(guard.elbowRBend).toBeGreaterThan(1.5);
    expect(left.elbowLBend).toBeLessThan(0.4); // left arm straight out…
    expect(left.elbowRBend).toBeGreaterThan(1.5); // …while the right stays in the guard
    expect(right.elbowRBend).toBeLessThan(0.4);
    expect(right.elbowLBend).toBeGreaterThan(1.5);
    expect(left.bodyYaw).toBeLessThan(0); // the punching shoulder comes forward
    expect(right.bodyYaw).toBeGreaterThan(0);
  });

  it('act_swimmer strokes with the arms half a cycle apart, leaning forward', () => {
    expect(range('act_swimmer', 'armLForward')).toBeGreaterThan(2);
    expect(sampleFor('act_swimmer', 0.25).armLForward).toBeCloseTo(
      sampleFor('act_swimmer', 0.75).armRForward,
      6,
    );
    expect(sampleFor('act_swimmer', 0.4).bodyBow).toBeGreaterThan(0.2);
  });

  it('act_robot snaps between right-angle poses and freezes in each', () => {
    const frozenA = sampleFor('act_robot', 0.1);
    const frozenB = sampleFor('act_robot', 0.2);
    expect(frozenA).toEqual(frozenB); // holding still inside a step
    expect(sampleFor('act_robot', 0.35)).not.toEqual(frozenA); // the next step is another pose
    expect(frozenA.elbowRBend).toBeCloseTo(Math.PI / 2, 6);
  });

  it('the acting loops are all different from each other', () => {
    const signature = (name: string): string =>
      [0.13, 0.37, 0.61, 0.88]
        .map((p) =>
          Object.values(sampleFor(name, p))
            .map((v) => v.toFixed(2))
            .join(','),
        )
        .join('|');
    const signatures = ACT_MOTION_NAMES.map(signature);
    expect(new Set(signatures).size).toBe(ACT_MOTION_NAMES.length);
  });

  it('duel_ready holds a tense stance: hands out by the hips, hardly moving', () => {
    const ready = sampleFor('duel_ready', 0.3);
    expect(ready.armLRaise).toBeGreaterThan(0.3);
    expect(ready.armRRaise).toBeGreaterThan(0.3);
    expect(ready.elbowLBend).toBeGreaterThan(0.4);
    for (const key of ['armLRaise', 'armRForward', 'bodyBow', 'headPitch'] as const) {
      expect(range('duel_ready', key)).toBeLessThan(0.05);
    }
  });

  it('duel_draw whips the right arm up to point forward within a fraction of a second', () => {
    const draw = PROCEDURAL_MOTIONS['duel_draw'];
    if (!draw) throw new Error('duel_draw');
    const aimAfterS = 0.1 * draw.durationS;
    expect(aimAfterS).toBeLessThan(0.2);
    expect(draw.attackS).toBeLessThan(0.1);
    const aimed = draw.sample(0.5);
    expect(aimed.armRForward).toBeCloseTo(Math.PI / 2, 2); // straight ahead
    expect(aimed.elbowRBend).toBeLessThan(0.2);
    expect(draw.sample(0.1).armRForward).toBeCloseTo(Math.PI / 2, 2);
  });

  it('duel_hit is thrown back first and slumps forward afterwards', () => {
    expect(sampleFor('duel_hit', 0.09).bodyBow).toBeLessThan(-0.15);
    expect(sampleFor('duel_hit', 0.09).armLRaise).toBeGreaterThan(1);
    const slump = sampleFor('duel_hit', 0.75);
    expect(slump.bodyBow).toBeGreaterThan(0.25);
    expect(slump.headPitch).toBeGreaterThan(0.4);
  });

  it('duel_win pumps the fist up twice', () => {
    const low = sampleFor('duel_win', 0.5).armRForward;
    const firstHigh = sampleFor('duel_win', 0.25).armRForward;
    const secondHigh = sampleFor('duel_win', 0.75).armRForward;
    expect(firstHigh).toBeGreaterThan(2.4);
    expect(secondHigh).toBeGreaterThan(2.4);
    expect(low).toBeLessThan(1.6);
  });

  it('sad looks down, bow bends from the feet, shrug lifts both forearms', () => {
    expect(sampleFor('sad', 0.5).headPitch).toBeGreaterThan(0.3);
    expect(sampleFor('bow', 0.5).bodyBow).toBeGreaterThan(0.4);
    const shrug = sampleFor('shrug', 0.5);
    expect(shrug.elbowLBend).toBeGreaterThan(1);
    expect(shrug.elbowRBend).toBeCloseTo(shrug.elbowLBend, 6);
  });
});

describe('pose helpers', () => {
  it('pulse peaks at its centre, is 0 outside its width, and wraps around the loop', () => {
    expect(pulse(0.25, 0.25, 0.1)).toBe(1);
    expect(pulse(0.4, 0.25, 0.1)).toBe(0);
    expect(pulse(0.2, 0.25, 0.1)).toBeGreaterThan(0);
    expect(pulse(0.98, 0.02, 0.1)).toBeCloseTo(pulse(0.06, 0.02, 0.1), 9);
    expect(pulse(0, 0.02, 0.1)).toBeCloseTo(pulse(1, 0.02, 0.1), 9);
  });

  it('throughKeys passes through every keyframe and clamps at the ends', () => {
    const a = { ...REST, headYaw: 1 };
    const b = { ...REST, headYaw: 3 };
    const keys = [
      [0.2, a],
      [0.6, b],
    ] as const;
    expect(throughKeys(0, keys)).toEqual(a);
    expect(throughKeys(0.2, keys)).toEqual(a);
    expect(throughKeys(0.4, keys).headYaw).toBeCloseTo(2, 6);
    expect(throughKeys(0.6, keys)).toEqual(b);
    expect(throughKeys(1, keys)).toEqual(b);
    expect(throughKeys(0.5, [])).toEqual(REST);
    expect(mixPoses(a, b, 0.25).headYaw).toBeCloseTo(1.5);
  });

  it('sampleMotion ignores names that only exist on Object.prototype', () => {
    expect(sampleMotion('constructor', 1)).toEqual(REST);
  });
});
