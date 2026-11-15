import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InteractionController, TICK_MS, type ReactionTarget } from './interactionController';
import { REACTION_TIMING as T } from './reactionPolicy';

function recordingTarget(): ReactionTarget & { readonly log: string[] } {
  const log: string[] = [];
  return {
    log,
    playMotion: (name) => log.push(`motion:${name}`),
    setBaseMotion: (name, interrupt) => log.push(`base:${name}${interrupt ? '!' : ''}`),
    flashFace: (face) => log.push(`face:${face ? (face.eyes ?? 'cheeks') : 'clear'}`),
    setDozing: (on) => log.push(`dozing:${on}`),
  };
}

describe('InteractionController (fake timers)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });
  afterEach(() => vi.useRealTimers());

  it('applies a click reaction at once: motion, then face', () => {
    const target = recordingTarget();
    const interaction = new InteractionController({ target, random: () => 0 });
    interaction.click();
    expect(target.log).toEqual(['motion:poke', 'face:happy']);
  });

  it('dances for ~3 s after a double click, then goes back to idle', () => {
    const target = recordingTarget();
    const interaction = new InteractionController({ target, random: () => 0.9 });
    interaction.click();
    vi.advanceTimersByTime(150);
    interaction.click();
    expect(target.log.at(-2)).toBe('motion:dance');
    vi.advanceTimersByTime(T.danceMs - 1);
    expect(target.log).not.toContain('base:idle!');
    vi.advanceTimersByTime(1);
    expect(target.log.at(-1)).toBe('base:idle!');
  });

  it('cancels the pending "back to idle" step when the brain takes over', () => {
    const target = recordingTarget();
    const interaction = new InteractionController({ target, random: () => 0.9 });
    interaction.click();
    vi.advanceTimersByTime(150);
    interaction.click(); // dance
    interaction.brain('speaking');
    expect(target.log.at(-2)).toBe('base:talk!');
    vi.advanceTimersByTime(T.danceMs * 2);
    expect(target.log).not.toContain('base:idle!');
  });

  it('runs the idle timeline from its own ticker: fidget at ~20 s, sleep at ~2 min', () => {
    const target = recordingTarget();
    const interaction = new InteractionController({ target, random: () => 0.5 });
    interaction.start();
    vi.advanceTimersByTime(T.fidgetAfterMs - TICK_MS);
    expect(target.log).toEqual([]);
    vi.advanceTimersByTime(TICK_MS);
    expect(target.log[0]).toMatch(/^motion:/);
    vi.advanceTimersByTime(T.sleepAfterMs);
    expect(target.log).toContain('motion:yawn');
    expect(target.log.at(-2)).toBe('dozing:true');
    expect(target.log.at(-1)).toBe('base:sleep');
    target.log.length = 0;
    interaction.click(); // wake up: surprised, then happy
    expect(target.log.slice(0, 3)).toEqual(['dozing:false', 'base:idle!', 'motion:surprised']);
    vi.advanceTimersByTime(T.wakeSurpriseMs);
    expect(target.log).toContain('motion:happy');
    interaction.dispose();
  });

  it('gets shy while the cursor rests on Pipi and stops when it leaves', () => {
    const target = recordingTarget();
    const interaction = new InteractionController({ target, random: () => 0.9 });
    interaction.start();
    interaction.hover(true);
    vi.advanceTimersByTime(T.hoverMs + TICK_MS);
    expect(target.log).toEqual(['motion:shy', 'face:happy']);
    interaction.hover(false);
    expect(target.log.slice(-2)).toEqual(['base:idle!', 'face:clear']);
    interaction.dispose();
  });

  it('stays quiet in calm mode', () => {
    const target = recordingTarget();
    const interaction = new InteractionController({ target });
    interaction.setCalm(true);
    interaction.start();
    interaction.hover(true);
    vi.advanceTimersByTime(T.sleepAfterMs * 2);
    expect(target.log).toEqual([]);
    interaction.click();
    expect(target.log).toEqual(['motion:poke', 'face:happy']);
    interaction.dispose();
  });

  it('keeps going if the pet throws while applying a step', () => {
    const target = recordingTarget();
    const broken: ReactionTarget = {
      ...target,
      playMotion: () => {
        throw new Error('view gone');
      },
    };
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const interaction = new InteractionController({ target: broken, random: () => 0 });
    expect(() => interaction.click()).not.toThrow();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
