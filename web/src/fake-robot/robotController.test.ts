import { BrainToBody, type EyeState, type WithoutEnvelope } from '@pipi/shared';
import { describe, expect, it, vi } from 'vitest';
import type { BaseLoop } from './motionPlan';
import {
  RobotController,
  SLEEP_SETTLE_MS,
  TRANSITION_CAP_MS,
  restingLoopFor,
  type MotionHandle,
  type RobotView,
} from './robotController';

/** A promise the test resolves by hand (an animation that finishes when we say so). */
function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve = (): void => undefined;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

class FakeView implements RobotView {
  readonly eyes: EyeState[] = [];
  readonly bases: [BaseLoop, boolean][] = [];
  readonly performed: string[] = [];
  readonly known = new Set(['wake_up', 'nod', 'signature_wave']);
  pending = new Map<string, () => void>();
  level = 0;

  setEyes(state: EyeState): void {
    this.eyes.push(state);
  }
  setSpeechLevel(level: number): void {
    this.level = level;
  }
  setBase(loop: BaseLoop, interrupt: boolean): void {
    this.bases.push([loop, interrupt]);
  }
  perform(name: string): MotionHandle | null {
    this.performed.push(name);
    if (!this.known.has(name)) return null;
    const done = deferred();
    this.pending.set(name, done.resolve);
    return { finished: done.promise };
  }
  finish(name: string): void {
    this.pending.get(name)?.();
  }
}

/** wait() that only resolves when the test advances it. */
class ManualWait {
  private readonly timers: { ms: number; resolve: () => void }[] = [];
  readonly wait = (ms: number): Promise<void> =>
    new Promise((resolve) => this.timers.push({ ms, resolve }));
  fire(ms: number): void {
    for (const timer of this.timers.filter((t) => t.ms === ms)) timer.resolve();
  }
  get requested(): number[] {
    return this.timers.map((t) => t.ms);
  }
}

function setup(startAwake = false) {
  const view = new FakeView();
  const speech = {
    speak: vi.fn(async () => ({ ok: true })),
    interrupt: vi.fn(),
  };
  const caption = { show: vi.fn(), hide: vi.fn() };
  const timers = new ManualWait();
  const robot = new RobotController({ view, speech, caption, startAwake, wait: timers.wait });
  return { robot, view, speech, caption, timers };
}

let nextId = 0;
/** A validated brain message, as the brain client hands it over. */
const message = (payload: WithoutEnvelope<BrainToBody>): BrainToBody =>
  BrainToBody.parse({ ...payload, id: `m${(nextId += 1)}`, ts: 1 });

const flush = async (): Promise<void> => {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
};

describe('RobotController start', () => {
  it('starts asleep with the eye displays off', () => {
    const { robot, view } = setup();
    expect(robot.awake).toBe(false);
    expect(view.eyes).toEqual(['off']);
    expect(view.bases).toEqual([['sleep', true]]);
  });

  it('can start awake (?awake=1)', () => {
    const { robot, view } = setup(true);
    expect(robot.awake).toBe(true);
    expect(view.eyes).toEqual(['idle']);
    expect(view.bases).toEqual([['idle', true]]);
  });
});

describe('activate wake_up', () => {
  it('acks only after the wake-up animation has finished, then shows idle eyes', async () => {
    const { robot, view } = setup();
    let acked = false;
    const ack = robot.handle(message({ type: 'activate', entrance: 'wake_up' })).then((r) => {
      acked = true;
      return r;
    });
    await flush();
    expect(view.performed).toEqual(['wake_up']);
    expect(view.eyes.at(-1)).toBe('sleepy'); // eyes come on drowsy
    expect(view.bases.at(-1)).toEqual(['idle', false]); // idle waits for wake_up to end
    expect(acked).toBe(false);
    view.finish('wake_up');
    expect(await ack).toEqual({ ok: true });
    expect(view.eyes.at(-1)).toBe('idle');
    expect(robot.awake).toBe(true);
  });

  it('acks at the cap if the animation never reports that it finished', async () => {
    const { robot, timers } = setup();
    const ack = robot.handle(message({ type: 'activate', entrance: 'wake_up' }));
    await flush();
    expect(timers.requested).toContain(TRANSITION_CAP_MS);
    timers.fire(TRANSITION_CAP_MS);
    expect((await ack).ok).toBe(true);
  });

  it('treats every entrance as a wake-up and acks at once when already awake', async () => {
    const { robot, view } = setup(true);
    expect(await robot.handle(message({ type: 'activate', entrance: 'jump_in' }))).toEqual({
      ok: true,
    });
    expect(view.performed).toEqual([]);
  });
});

describe('deactivate sleep', () => {
  it('stops talking, slumps into sleep and acks once the eyes are off', async () => {
    const { robot, view, speech, caption, timers } = setup(true);
    const ack = robot.handle(message({ type: 'deactivate', exit: 'sleep' }));
    await flush();
    expect(speech.interrupt).toHaveBeenCalled();
    expect(caption.hide).toHaveBeenCalled();
    expect(view.bases.at(-1)).toEqual(['sleep', true]);
    expect(view.eyes.at(-1)).toBe('sleepy');
    timers.fire(SLEEP_SETTLE_MS);
    expect((await ack).ok).toBe(true);
    expect(view.eyes.at(-1)).toBe('off');
    expect(robot.awake).toBe(false);
  });

  it('acks at once when already asleep', async () => {
    const { robot, view } = setup();
    expect((await robot.handle(message({ type: 'deactivate', exit: 'fade_out' }))).ok).toBe(true);
    expect(view.eyes).toEqual(['off']);
  });

  it('a wake-up right after a sleep keeps the eyes on', async () => {
    const { robot, view, timers } = setup(true);
    const sleeping = robot.handle(message({ type: 'deactivate', exit: 'sleep' }));
    await flush();
    const waking = robot.handle(message({ type: 'activate', entrance: 'wake_up' }));
    await flush();
    view.finish('wake_up');
    await waking;
    timers.fire(SLEEP_SETTLE_MS);
    await sleeping;
    expect(view.eyes.at(-1)).toBe('idle');
    expect(robot.awake).toBe(true);
  });
});

describe('speak, eyes, motion and pet-only messages', () => {
  it('passes speak to the speech service and shows the expression', async () => {
    const { robot, view, speech } = setup(true);
    const msg = message({ type: 'speak', text: 'Ta-da!', expression: 'happy' });
    expect(await robot.handle(msg)).toEqual({ ok: true });
    expect(speech.speak).toHaveBeenCalledWith(msg);
    expect(view.eyes.at(-1)).toBe('happy');
  });

  it('returns the speech refusal so the brain can fall back to the laptop speaker', async () => {
    const { robot, speech } = setup(true);
    speech.speak.mockResolvedValueOnce({ ok: false, error: 'audio could not be played' } as never);
    const result = await robot.handle(message({ type: 'speak', text: 'hi', expression: 'idle' }));
    expect(result.ok).toBe(false);
  });

  it('talks in the talk loop and rests in the loop that matches the eyes', async () => {
    const { robot, view } = setup(true);
    await robot.handle(message({ type: 'eyes', state: 'listening' }));
    expect(view.bases.at(-1)).toEqual(['listen', false]);
    robot.setTalking(true);
    expect(view.bases.at(-1)).toEqual(['talk', false]);
    robot.setTalking(false);
    expect(view.bases.at(-1)).toEqual(['listen', false]);
  });

  it('keeps sleeping while asleep, whatever the eyes do', async () => {
    const { robot, view } = setup();
    await robot.handle(message({ type: 'eyes', state: 'thinking' }));
    robot.setTalking(true);
    expect(view.bases).toEqual([['sleep', true]]);
  });

  it('remembers eye states but not one-shot blinks', async () => {
    const { robot, view } = setup(true);
    await robot.handle(message({ type: 'eyes', state: 'surprised' }));
    await robot.handle(message({ type: 'eyes', state: 'blink' }));
    expect(view.eyes.at(-1)).toBe('blink');
    expect(robot.currentEyes).toBe('surprised');
  });

  it('acks motions at once, refusing unknown ones', async () => {
    const { robot } = setup(true);
    expect(await robot.handle(message({ type: 'motion', name: 'nod' }))).toEqual({ ok: true });
    expect(await robot.handle(message({ type: 'motion', name: 'moonwalk' }))).toEqual({
      ok: false,
      error: 'unknown motion: moonwalk',
    });
  });

  it('shows and hides captions', async () => {
    const { robot, caption } = setup(true);
    await robot.handle(message({ type: 'caption', text: 'hello' }));
    await robot.handle(message({ type: 'caption', text: null }));
    expect(caption.show).toHaveBeenCalledWith('hello');
    expect(caption.hide).toHaveBeenCalled();
  });

  it('acknowledges pet-only messages without doing anything', async () => {
    const { robot, view } = setup(true);
    expect((await robot.handle(message({ type: 'body_config', robot_side: 'left' }))).ok).toBe(
      true,
    );
    expect((await robot.handle(message({ type: 'calm', on: true }))).ok).toBe(true);
    expect(view.eyes).toEqual(['idle']);
  });

  it('maps eye states to resting loops', () => {
    expect(restingLoopFor('listening')).toBe('listen');
    expect(restingLoopFor('thinking')).toBe('think');
    expect(restingLoopFor('happy')).toBe('idle');
  });
});
