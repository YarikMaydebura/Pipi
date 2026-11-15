import { describe, expect, it } from 'vitest';
import { REACTION_TIMING as T, ReactionPolicy, type Reaction } from './reactionPolicy';

const motions = (r: Reaction | null): string[] =>
  (r?.steps ?? []).flatMap((s) => (s.motion ? [s.motion] : []));

/** Clicks spaced so they are neither double clicks nor a burst. */
const SLOW_CLICK_MS = T.burstWindowMs + 100;

describe('ReactionPolicy: clicks', () => {
  it('reacts to a single click with poke, giggle or surprised and the matching face', () => {
    const policy = new ReactionPolicy(0, { random: () => 0.5 });
    const reaction = policy.click(1000);
    expect(reaction?.name).toBe('poke:giggle');
    const step = reaction?.steps[0];
    expect(step?.motion).toBe('giggle');
    expect(step?.face).toMatchObject({ eyes: 'happy', mouth: 'big_smile', cheeks: true });
  });

  it('never picks the same click reaction twice in a row', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 }); // always "the first option"
    const picks: string[] = [];
    for (let i = 1; i <= 6; i += 1) picks.push(...motions(policy.click(i * SLOW_CLICK_MS)));
    expect(picks).toHaveLength(6);
    for (let i = 1; i < picks.length; i += 1) expect(picks[i]).not.toBe(picks[i - 1]);
    expect(new Set(picks)).toEqual(new Set(['poke', 'giggle']));
  });

  it('gives surprised a small "o" mouth', () => {
    const policy = new ReactionPolicy(0, { random: () => 0.99 });
    const step = policy.click(1000)?.steps[0];
    expect(step?.motion).toBe('surprised');
    expect(step?.face).toMatchObject({ eyes: 'surprised', mouth: 'small_o' });
  });

  it('turns a double click into spin or dance, and dance returns to idle after ~3 s', () => {
    const spinner = new ReactionPolicy(0, { random: () => 0 });
    spinner.click(1000);
    expect(spinner.click(1000 + T.doubleClickMs - 50)?.name).toBe('double:spin');

    const dancer = new ReactionPolicy(0, { random: () => 0.9 });
    dancer.click(1000);
    const dance = dancer.click(1200);
    expect(dance?.name).toBe('double:dance');
    expect(dance?.steps.at(-1)).toEqual({
      atMs: T.danceMs,
      base: { name: 'idle', interrupt: true },
    });
  });

  it('does not let a single click cut a running spin', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    policy.click(1000);
    policy.click(1200); // spin
    expect(policy.click(1400)).toBeNull(); // third quick click: not another double
  });

  it('celebrates (or giggles) at the 4th click within 3 s and shakes its head at the 7th', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    const names: (string | undefined)[] = [];
    for (let i = 0; i < T.tooManyClicks; i += 1) names.push(policy.click(1000 + i * 400)?.name);
    expect(names[T.burstClicks - 1]).toBe('burst:celebrate');
    expect(names.at(-1)).toBe('stop:shake_head');
    // The 5th and 6th clicks are absorbed by the running celebration.
    expect(names[T.burstClicks]).toBeUndefined();
  });

  it('stops counting clicks older than the burst window', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    for (let i = 0; i < 3; i += 1) policy.click(1000 + i * 400);
    expect(policy.click(1000 + T.burstWindowMs + 1000)?.name).toMatch(/^poke:/);
  });

  it('with reduced motion: no spin, dance or celebrate', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    policy.setReducedMotion(true);
    policy.click(1000);
    expect(policy.click(1200)?.name).toBe('double:happy');
    const burst = new ReactionPolicy(0, { random: () => 0 });
    burst.setReducedMotion(true);
    const names = [0, 1, 2, 3].map((i) => burst.click(1000 + i * 500)?.name);
    expect(names[3]).toBe('burst:giggle');
  });
});

describe('ReactionPolicy: priorities', () => {
  it('never interrupts brain-driven speech: a click only lights the cheeks', () => {
    const policy = new ReactionPolicy(0);
    expect(policy.brain('speaking', 100)?.steps[0]?.base).toEqual({
      name: 'talk',
      interrupt: false,
    });
    const reaction = policy.click(500);
    expect(reaction?.name).toBe('acknowledge');
    expect(motions(reaction)).toEqual([]);
    expect(reaction?.steps[0]?.base).toBeUndefined();
  });

  it('maps brain activity to rest loops and cuts a running click reaction', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    policy.click(1000); // the pet owns the body for a moment
    expect(policy.brain('listening', 1100)?.steps[0]?.base).toEqual({
      name: 'listen',
      interrupt: true,
    });
    expect(policy.brain('thinking', 2000)?.steps[0]?.base?.name).toBe('think');
    expect(policy.brain('idle', 3000)?.steps[0]?.base?.name).toBe('idle');
  });

  it('lets a brain motion cancel pending steps without touching the body', () => {
    const policy = new ReactionPolicy(0);
    expect(policy.brain('idle', 100, 'celebrate')).toEqual({ name: 'brain', steps: [] });
    expect(policy.brain('idle', 200)).toBeNull(); // nothing changed
  });

  it('does nothing at all while migrating or away (never interrupts jump_out / jump_in)', () => {
    const policy = new ReactionPolicy(0);
    expect(policy.brain('migrating', 100)).toBeNull();
    expect(policy.click(200)).toBeNull();
    expect(policy.drag(true, 300)).toBeNull();
    expect(policy.tick(10 * T.sleepAfterMs)).toBeNull();
    policy.brain('away', 400);
    policy.hover(true, 500);
    expect(policy.tick(5000)).toBeNull();
  });

  it('lets the brain win over a drag', () => {
    const policy = new ReactionPolicy(0);
    policy.brain('speaking', 100);
    expect(policy.drag(true, 200)).toBeNull();
    // The brain finishes while Pipi is still held: back to dangling.
    expect(policy.brain('idle', 300)?.steps[0]?.base?.name).toBe('dangle');
  });

  it('dangles while dragged and lands on release', () => {
    const policy = new ReactionPolicy(0);
    const start = policy.drag(true, 1000);
    expect(start?.steps[0]?.base).toEqual({ name: 'dangle', interrupt: true });
    expect(policy.click(1100)).toBeNull(); // no click reactions mid-drag
    const end = policy.drag(false, 3000);
    expect(end?.steps[0]).toMatchObject({
      base: { name: 'idle', interrupt: true },
      motion: 'land',
    });
  });
});

describe('ReactionPolicy: hover', () => {
  it('gets shy after hovering ~1.5 s, and leaving ends it', () => {
    const policy = new ReactionPolicy(0, { random: () => 0.9 }); // 0.9 ≥ love chance → shy
    expect(policy.hover(true, 1000)).toBeNull();
    expect(policy.tick(1000 + T.hoverMs - 100)).toBeNull();
    const shy = policy.tick(1000 + T.hoverMs);
    expect(shy?.name).toBe('hover:shy');
    expect(policy.tick(1000 + T.hoverMs + 500)).toBeNull(); // only once per hover
    const leave = policy.hover(false, 4000);
    expect(leave?.steps[0]).toEqual({
      atMs: 0,
      face: 'clear',
      base: { name: 'idle', interrupt: true },
    });
  });

  it('sometimes shows heart eyes instead', () => {
    const policy = new ReactionPolicy(0, { random: () => 0.1 });
    policy.hover(true, 0);
    const love = policy.tick(T.hoverMs);
    expect(love?.name).toBe('hover:love');
    expect(love?.steps[0]?.face).toMatchObject({ eyes: 'love', cheeks: true });
  });

  it('leaving without a reaction does nothing', () => {
    const policy = new ReactionPolicy(0);
    policy.hover(true, 0);
    expect(policy.hover(false, 500)).toBeNull();
  });
});

describe('ReactionPolicy: idle timeline', () => {
  it('fidgets first after ~20 s, then every 15–30 s, never the same twice in a row', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    expect(policy.tick(T.fidgetAfterMs - 1)).toBeNull();
    const first = policy.tick(T.fidgetAfterMs);
    expect(first?.name).toBe('fidget:look_around');
    expect(first?.steps.at(-1)?.base?.name).toBe('idle'); // look_around ends after a while
    // random() = 0 → the shortest gap.
    expect(policy.tick(T.fidgetAfterMs + T.fidgetMinMs - 1)).toBeNull();
    const second = policy.tick(T.fidgetAfterMs + T.fidgetMinMs);
    expect(second?.name).toBe('fidget:yawn');
    expect(second?.steps[0]?.face).toMatchObject({ eyes: 'sleepy' });
  });

  it('waits the longest gap with random() close to 1, and twice as long with reduced motion', () => {
    const policy = new ReactionPolicy(0, { random: () => 0.999 });
    policy.tick(T.fidgetAfterMs); // gap ≈ max
    expect(policy.tick(T.fidgetAfterMs + T.fidgetMaxMs - 100)).toBeNull();
    expect(policy.tick(T.fidgetAfterMs + T.fidgetMaxMs)).not.toBeNull();

    const reduced = new ReactionPolicy(0);
    reduced.setReducedMotion(true);
    reduced.click(0); // restarts the timeline with the reduced factor
    expect(reduced.tick(T.fidgetAfterMs + 500)).toBeNull();
    expect(reduced.tick(T.fidgetAfterMs * T.reducedFidgetFactor + 2000)).not.toBeNull();
  });

  it('yawns and falls asleep after 2 min without interaction; a click wakes it', () => {
    const policy = new ReactionPolicy(0, { random: () => 0.5, timing: { fidgetAfterMs: 1e9 } });
    expect(policy.tick(T.sleepAfterMs - 1)).toBeNull();
    const sleep = policy.tick(T.sleepAfterMs);
    expect(sleep?.name).toBe('sleep');
    expect(sleep?.steps.at(-1)).toMatchObject({ dozing: true, base: { name: 'sleep' } });
    expect(policy.isDozing).toBe(true);
    expect(policy.tick(T.sleepAfterMs + 60_000)).toBeNull(); // stays asleep

    const wake = policy.click(T.sleepAfterMs + 70_000);
    expect(wake?.name).toBe('wake');
    expect(wake?.steps[0]).toMatchObject({ dozing: false, motion: 'surprised' });
    expect(wake?.steps[1]).toMatchObject({ atMs: T.wakeSurpriseMs, motion: 'happy' });
    expect(policy.isDozing).toBe(false);
  });

  it('wakes quietly when the brain says something', () => {
    const policy = new ReactionPolicy(0, { timing: { fidgetAfterMs: 1e9 } });
    policy.tick(T.sleepAfterMs);
    const reaction = policy.brain('idle', T.sleepAfterMs + 5000);
    expect(reaction?.steps[0]).toMatchObject({ dozing: false, base: { name: 'idle' } });
  });

  it('does not fidget while the brain is busy', () => {
    const policy = new ReactionPolicy(0);
    policy.brain('listening', 0);
    expect(policy.tick(T.sleepAfterMs * 2)).toBeNull();
  });
});

describe('ReactionPolicy: calm mode', () => {
  it('has no fidgets, no sleep and no hover reactions', () => {
    const policy = new ReactionPolicy(0);
    policy.setCalm(true, 0);
    policy.hover(true, 100);
    for (let t = 0; t <= T.sleepAfterMs * 2; t += 250) expect(policy.tick(t)).toBeNull();
  });

  it('answers clicks with a tiny poke only, never escalating', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    policy.setCalm(true, 0);
    const names = [0, 1, 2, 3, 4, 5, 6].map((i) => policy.click(1000 + i * 200)?.name);
    expect(names.filter((n) => n !== undefined).every((n) => n === 'calm:poke')).toBe(true);
    expect(names[0]).toBe('calm:poke');
  });

  it('wakes a dozing Pipi when calm mode starts', () => {
    const policy = new ReactionPolicy(0, { timing: { fidgetAfterMs: 1e9 } });
    policy.tick(T.sleepAfterMs);
    expect(policy.setCalm(true, T.sleepAfterMs + 1000)?.steps[0]).toMatchObject({ dozing: false });
    expect(policy.isDozing).toBe(false);
  });

  it('fidgets again after calm mode ends', () => {
    const policy = new ReactionPolicy(0, { random: () => 0 });
    policy.setCalm(true, 0);
    policy.setCalm(false, 1000);
    expect(policy.tick(1000 + T.fidgetAfterMs)?.name).toMatch(/^fidget:/);
  });
});
