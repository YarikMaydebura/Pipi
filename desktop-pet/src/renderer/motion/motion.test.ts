import { describe, expect, it } from 'vitest';
import { idlePose, lookAt, NO_LOOK } from './idle';
import { isLoopMotion, MOTION_BLEND_S, MOTION_NAMES, MOTIONS, MotionPlayer } from './motions';
import { addPoses, damp, dampTravel, hold, pose, ZERO_POSE } from './pose';

describe('motions', () => {
  const oneShots = MOTION_NAMES.filter((name) => !isLoopMotion(name));
  const loops = MOTION_NAMES.filter(isLoopMotion);

  it.each(oneShots)('%s starts and ends at rest', (name) => {
    const def = MOTIONS[name];
    expect(def).toBeDefined();
    if (!def) return;
    expect(def.durationS).toBeGreaterThan(0);
    for (const p of [0, 1]) {
      const sample = def.sample(p);
      for (const value of Object.values(sample)) expect(Math.abs(value)).toBeLessThan(0.02);
    }
  });

  it.each(loops)('%s loops seamlessly (the end matches the start)', (name) => {
    const def = MOTIONS[name];
    if (!def) throw new Error(`missing ${name}`);
    const start = def.sample(0);
    const end = def.sample(1);
    for (const key of Object.keys(start) as (keyof typeof start)[]) {
      expect(end[key]).toBeCloseTo(start[key], 5);
    }
  });

  it('player rejects unknown names and returns to rest after a motion', () => {
    const player = new MotionPlayer();
    expect(player.play('moonwalk', 0)).toBe(false);
    expect(player.play('nod', 0)).toBe(true);
    expect(player.isPlaying(0.3)).toBe(true);
    expect(player.sample(0.25).headPitch).toBeGreaterThan(0);
    expect(player.sample(5)).toEqual(ZERO_POSE);
    expect(player.isPlaying(5)).toBe(false);
  });

  it('loops talk until idle stops it', () => {
    const player = new MotionPlayer();
    player.play('talk', 0);
    expect(player.isPlaying(60)).toBe(true);
    expect(player.play('idle', 60)).toBe(true);
    expect(player.isPlaying(60)).toBe(false);
  });
});

describe('MotionPlayer base loop', () => {
  it('rests in the base loop and returns to it after a one-shot, blending', () => {
    const player = new MotionPlayer();
    expect(player.setBase('sleep', 0, false)).toBe(true);
    expect(player.sample(1).headPitch).toBeGreaterThan(0.3); // sleeping: head down
    player.play('nod', 2);
    expect(player.sample(2 + MOTION_BLEND_S / 2).headPitch).toBeGreaterThan(0); // blending
    player.sample(10); // nod over
    const settled = player.sample(10 + MOTION_BLEND_S + 0.01);
    expect(settled.headPitch).toBeGreaterThan(0.3); // back asleep
  });

  it('lets a one-shot finish unless the base change interrupts it', () => {
    const player = new MotionPlayer();
    player.play('celebrate', 0);
    player.setBase('dangle', 0.1, false);
    expect(player.isPlaying(0.2)).toBe(true);
    player.setBase('talk', 0.3, true);
    expect(player.isPlaying(0.4)).toBe(false);
  });

  it('accepts only loops (or idle) as the base', () => {
    const player = new MotionPlayer();
    expect(player.setBase('nod', 0, false)).toBe(false);
    expect(player.setBase('moonwalk', 0, false)).toBe(false);
    expect(player.setBase('idle', 0, false)).toBe(true);
    expect(player.sample(1)).toEqual(ZERO_POSE);
  });

  it('never snaps: a switch starts from the previous pose', () => {
    const player = new MotionPlayer();
    player.setBase('sleep', 0, false);
    const before = player.sample(1);
    player.setBase('idle', 1, true);
    expect(player.sample(1).headPitch).toBeCloseTo(before.headPitch, 5);
    expect(player.sample(1 + MOTION_BLEND_S + 0.01)).toEqual(ZERO_POSE);
  });
});

describe('pose helpers', () => {
  it('adds poses field by field', () => {
    const sum = addPoses(pose({ headYaw: 0.1 }), pose({ headYaw: 0.2, squash: 0.05 }));
    expect(sum.headYaw).toBeCloseTo(0.3);
    expect(sum.squash).toBeCloseTo(0.05);
  });

  it('scales only travelling movement for reduced motion', () => {
    const reduced = dampTravel(pose({ bodyLift: 0.1, headYaw: 0.4 }), 0.5);
    expect(reduced.bodyLift).toBeCloseTo(0.05);
    expect(reduced.headYaw).toBeCloseTo(0.4);
  });

  it('damp approaches the target and hold ramps 0 → 1 → 0', () => {
    expect(damp(0, 1, 5, 10)).toBeCloseTo(1);
    expect(damp(0, 1, 5, 0)).toBe(0);
    expect(hold(0)).toBe(0);
    expect(hold(0.5)).toBe(1);
    expect(hold(1)).toBe(0);
  });
});

describe('idle and look-at', () => {
  it('keeps still with reduced motion', () => {
    expect(idlePose(3, true)).toEqual(ZERO_POSE);
    expect(idlePose(3, false)).not.toEqual(ZERO_POSE);
  });

  it('turns toward the cursor within limits', () => {
    const head = { x: 160, y: 200 };
    expect(lookAt(null, head)).toEqual(NO_LOOK);
    const right = lookAt({ x: 900, y: 200 }, head);
    expect(right.yaw).toBeGreaterThan(0);
    expect(right.gazeX).toBeGreaterThan(0);
    const farLeftUp = lookAt({ x: -50_000, y: -50_000 }, head);
    expect(farLeftUp.yaw).toBeGreaterThanOrEqual(-0.55);
    expect(farLeftUp.pitch).toBeGreaterThanOrEqual(-0.3);
    expect(farLeftUp.gazeX).toBe(-1);
  });
});
