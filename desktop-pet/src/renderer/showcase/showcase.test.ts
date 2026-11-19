import { describe, expect, it } from 'vitest';
import type { ShowcaseStep } from './playlist';
import { Showcase, showcaseRequested, type ShowcaseActor } from './showcase';

const STEPS: readonly ShowcaseStep[] = [
  { kind: 'clip', title: 'wave', clip: 'signature_wave', eyes: 'happy', holdMs: 2000 },
  { kind: 'clip', title: 'love', clip: 'love', eyes: 'happy', holdMs: 2200, love: true },
  { kind: 'eyes', title: 'sad eyes', eyes: 'sad', holdMs: 1500 },
  { kind: 'speak', title: 'talking', text: 'Hi!', holdMs: 3000 },
  { kind: 'jump', title: 'jump' },
];

interface Fixture {
  readonly log: string[];
  readonly showcase: Showcase;
}

function setup(failingMotion?: string): Fixture {
  const log: string[] = [];
  const actor: ShowcaseActor = {
    setEyes: (state) => log.push(`eyes:${state}`),
    playMotion: (name) => {
      if (name === failingMotion) throw new Error('boom');
      log.push(`motion:${name}`);
    },
    loveFace: (durationMs) => log.push(`love:${durationMs}`),
    say: (text) => log.push(`say:${text}`),
    jumpOutAndBack: () => {
      log.push('jump');
      return Promise.resolve();
    },
  };
  const showcase = new Showcase({
    actor,
    steps: STEPS,
    onStep: (step, index, total) => log.push(`title:${step.title} ${index + 1}/${total}`),
    wait: (ms) => {
      log.push(`wait:${ms}`);
      return Promise.resolve();
    },
    onError: (step) => log.push(`error:${step.title}`),
  });
  return { log, showcase };
}

describe('Showcase', () => {
  it('plays every step in order: title, face, motion, then waits', async () => {
    const { log, showcase } = setup();

    await showcase.playOnce();

    expect(log).toEqual([
      'title:wave 1/5',
      'eyes:happy',
      'motion:signature_wave',
      'wait:2000',
      'title:love 2/5',
      'eyes:happy',
      'love:2200',
      'motion:love',
      'wait:2200',
      'title:sad eyes 3/5',
      'motion:idle', // leave a loop that may still be running
      'eyes:sad',
      'wait:1500',
      'title:talking 4/5',
      'motion:idle',
      'say:Hi!',
      'wait:3000',
      'title:jump 5/5',
      'eyes:happy',
      'jump',
    ]);
  });

  it('skips a step that fails and carries on with the show', async () => {
    const { log, showcase } = setup('signature_wave');

    await showcase.playOnce();

    expect(log.slice(0, 4)).toEqual([
      'title:wave 1/5',
      'eyes:happy',
      'error:wave',
      'title:love 2/5',
    ]);
    expect(log.at(-1)).toBe('jump');
  });

  it('stops between steps', async () => {
    const log: string[] = [];
    let showcase: Showcase | null = null;
    const actor: ShowcaseActor = {
      setEyes: () => undefined,
      playMotion: (name) => {
        log.push(name);
        showcase?.stop(); // e.g. the window is closing
      },
      loveFace: () => undefined,
      say: () => undefined,
      jumpOutAndBack: () => Promise.resolve(),
    };
    showcase = new Showcase({ actor, steps: STEPS, wait: () => Promise.resolve() });

    showcase.start();
    await showcase.finished;

    expect(log).toEqual(['signature_wave']);
  });

  it('is requested with ?showcase=1 only', () => {
    expect(showcaseRequested('?showcase=1')).toBe(true);
    expect(showcaseRequested('?debug=1&showcase=1')).toBe(true);
    expect(showcaseRequested('?showcase=0')).toBe(false);
    expect(showcaseRequested('')).toBe(false);
  });
});
