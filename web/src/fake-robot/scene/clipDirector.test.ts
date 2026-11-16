import { AnimationClip, NumberKeyframeTrack, Object3D } from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HELD_MAX_S } from '../motionPlan';
import { ClipDirector } from './clipDirector';

/** A one-second clip that moves the head; the weight of its action tells us what is playing. */
function clip(name: string): AnimationClip {
  return new AnimationClip(name, 1, [new NumberKeyframeTrack('head.position[y]', [0, 1], [0, 1])]);
}

function setup(names: readonly string[]): { director: ClipDirector } {
  const root = new Object3D();
  const head = new Object3D();
  head.name = 'head';
  root.add(head);
  return { director: new ClipDirector(root, names.map(clip)) };
}

/** Advance the mixer (and the fake timers) by `seconds`, in small frames. */
function run(director: ClipDirector, seconds: number): void {
  const frames = Math.round(seconds / 0.05);
  for (let i = 0; i < frames; i += 1) {
    director.update(0.05);
    vi.advanceTimersByTime(50);
  }
}

async function isSettled(promise: Promise<void>): Promise<boolean> {
  let settled = false;
  void promise.then(() => {
    settled = true;
  });
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  return settled;
}

const CLIPS = ['idle', 'talk', 'sleep', 'nod', 'act_bird', 'act_boxer', 'duel_ready', 'duel_draw'];

describe('ClipDirector', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('knows its clips by name, ignoring separators and case', () => {
    const { director } = setup(CLIPS);
    expect(director.clipCount).toBe(CLIPS.length);
    expect(director.has('act_bird')).toBe(true);
    expect(director.has('Act.Bird')).toBe(true);
    expect(director.has('moonwalk')).toBe(false);
    expect(director.play('moonwalk', { mode: 'once', seconds: 1 })).toBeNull();
  });

  it('a one-shot finishes by itself and returns to the base loop', async () => {
    const { director } = setup(CLIPS);
    director.setBase('idle', true);
    const finished = director.play('nod', { mode: 'once', seconds: 0 });
    if (!finished) throw new Error('nod should play');
    run(director, 0.5);
    expect(await isSettled(finished)).toBe(false);
    run(director, 0.8);
    expect(await isSettled(finished)).toBe(true);
  });

  it('a held loop keeps playing far beyond its own length', async () => {
    const { director } = setup(CLIPS);
    director.setBase('idle', true);
    const finished = director.play('act_bird', { mode: 'held', seconds: HELD_MAX_S });
    if (!finished) throw new Error('act_bird should play');
    run(director, 30);
    expect(await isSettled(finished)).toBe(false);
  });

  it('asking again for the held motion keeps it going (same handle, cap moved)', async () => {
    const { director } = setup(CLIPS);
    const first = director.play('act_bird', { mode: 'held', seconds: 10 });
    run(director, 8);
    const again = director.play('act_bird', { mode: 'held', seconds: 10 });
    expect(again).toBe(first);
    run(director, 8); // 16 s after the start: the first cap alone would have ended it
    if (!first) throw new Error('act_bird should play');
    expect(await isSettled(first)).toBe(false);
    run(director, 3);
    expect(await isSettled(first)).toBe(true); // the safety cap, counted from the re-send
  });

  it('the next motion ends a held one', async () => {
    const { director } = setup(CLIPS);
    const ready = director.play('duel_ready', { mode: 'held', seconds: HELD_MAX_S });
    run(director, 4);
    const draw = director.play('duel_draw', { mode: 'once', seconds: 0 });
    if (!ready || !draw) throw new Error('duel clips should play');
    expect(await isSettled(ready)).toBe(true);
    expect(await isSettled(draw)).toBe(false);
    run(director, 1.3);
    expect(await isSettled(draw)).toBe(true);
  });

  it('a base change with interrupt (what `stop` does) ends a held motion; without, it goes on', async () => {
    const { director } = setup(CLIPS);
    const acting = director.play('act_boxer', { mode: 'held', seconds: HELD_MAX_S });
    if (!acting) throw new Error('act_boxer should play');
    director.setBase('talk', false);
    run(director, 2);
    expect(await isSettled(acting)).toBe(false);
    director.setBase('idle', true);
    expect(await isSettled(acting)).toBe(true);
  });

  it('a held motion exported as a non-looping clip stays on its last frame', async () => {
    const { director } = setup(['idle', 'nod']); // `nod` is not a loop clip
    const held = director.play('nod', { mode: 'held', seconds: HELD_MAX_S });
    if (!held) throw new Error('nod should play');
    run(director, 5);
    expect(await isSettled(held)).toBe(false);
    director.endMotion();
    expect(await isSettled(held)).toBe(true);
  });

  it('a resting loop asked for as a gesture ends after its seconds', async () => {
    const { director } = setup(CLIPS);
    const talking = director.play('talk', { mode: 'timed', seconds: 3 });
    if (!talking) throw new Error('talk should play');
    run(director, 2.5);
    expect(await isSettled(talking)).toBe(false);
    run(director, 0.6);
    expect(await isSettled(talking)).toBe(true);
  });

  it('refuses a base loop the model does not have', () => {
    const { director } = setup(['idle']);
    expect(director.setBase('sleep', true)).toBe(false);
    expect(director.setBase('idle', true)).toBe(true);
  });
});
