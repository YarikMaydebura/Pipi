import { EyeState } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import { GLB_CLIPS, LOOPING_CLIPS, ONE_SHOT_CLIPS } from '../scene/partNames';
import { JUMP_CLIPS, SHOWCASE_STEPS, type ShowcaseStep } from './playlist';

const clipSteps = SHOWCASE_STEPS.filter(
  (step): step is Extract<ShowcaseStep, { kind: 'clip' }> => step.kind === 'clip',
);
/** The shortest one-shot clip in pipi.glb is `land` (0.58 s); nothing may be cut shorter. */
const SHORTEST_ONE_SHOT_MS = 580;
const LONGEST_LOOP_CYCLE_MS = 3000; // idle, sleep and look_around

describe('showcase playlist', () => {
  it('shows every animation clip of the model', () => {
    const shown = new Set<string>(clipSteps.map((step) => step.clip));
    const jumps = SHOWCASE_STEPS.some((step) => step.kind === 'jump') ? JUMP_CLIPS : [];

    const missing = GLB_CLIPS.filter((clip) => !shown.has(clip) && !jumps.includes(clip));

    expect(missing).toEqual([]);
  });

  it('shows every eye state', () => {
    const shown = new Set<string>(
      SHOWCASE_STEPS.flatMap((step) =>
        step.kind === 'clip' || step.kind === 'eyes' ? [step.eyes] : [],
      ),
    );

    expect(EyeState.options.filter((state) => !shown.has(state))).toEqual([]);
  });

  it('only names clips that exist', () => {
    expect(clipSteps.filter((step) => !GLB_CLIPS.includes(step.clip))).toEqual([]);
    expect(JUMP_CLIPS.every((clip) => GLB_CLIPS.includes(clip))).toBe(true);
  });

  it('gives one-shots time to finish and loops at least one full cycle', () => {
    for (const step of clipSteps) {
      const isLoop = LOOPING_CLIPS.includes(step.clip);
      expect(isLoop || ONE_SHOT_CLIPS.includes(step.clip)).toBe(true);
      expect(step.holdMs, step.title).toBeGreaterThan(isLoop ? 2000 : SHORTEST_ONE_SHOT_MS);
    }
    const sleep = clipSteps.find((step) => step.clip === 'sleep');
    expect(sleep?.holdMs).toBeGreaterThanOrEqual(LONGEST_LOOP_CYCLE_MS);
  });

  it('has a short title for every step', () => {
    for (const step of SHOWCASE_STEPS) {
      expect(step.title.length).toBeGreaterThan(0);
      expect(step.title.length).toBeLessThanOrEqual(28);
    }
  });
});
