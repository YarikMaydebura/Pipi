import { EyeState } from '@pipi/shared';
import { PALETTES } from '@pipi/shared/look';
import { describe, expect, it } from 'vitest';
import { CUE_COLORS, CUE_STRENGTH, cueForEyes, cueLook, GO_SOUND, soundLengthMs } from './duelCue';

const moving = (t: number, sinceS = t): { t: number; sinceS: number; reducedMotion: boolean } => ({
  t,
  sinceS,
  reducedMotion: false,
});
const still = (t: number, sinceS = t): { t: number; sinceS: number; reducedMotion: boolean } => ({
  t,
  sinceS,
  reducedMotion: true,
});

describe('duel cue', () => {
  it('only the two duel eye states have a scene cue', () => {
    expect(cueForEyes('countdown')).toBe('countdown');
    expect(cueForEyes('signal_go')).toBe('go');
    for (const state of EyeState.options) {
      if (state !== 'countdown' && state !== 'signal_go') expect(cueForEyes(state)).toBe('none');
    }
  });

  it('uses the eye colours: amber to wait, green to go', () => {
    expect(CUE_COLORS.countdown).toBe(PALETTES.amber.mid);
    expect(CUE_COLORS.go).toBe(PALETTES.green.mid);
    expect(cueLook('countdown', moving(3.2)).color).toBe(CUE_COLORS.countdown);
    expect(cueLook('go', moving(3.2)).color).toBe(CUE_COLORS.go);
    expect(cueLook('none', moving(3.2))).toEqual({ color: null, strength: 0 });
  });

  it('countdown pulses once per second, in step with the eye clock, and never goes dark', () => {
    const onBeat = cueLook('countdown', moving(7)).strength;
    const mid = cueLook('countdown', moving(7.5)).strength;
    const late = cueLook('countdown', moving(7.99)).strength;
    expect(onBeat).toBeCloseTo(CUE_STRENGTH.countdownBeat, 6);
    expect(mid).toBeLessThan(onBeat);
    expect(late).toBeLessThan(mid);
    expect(late).toBeGreaterThanOrEqual(CUE_STRENGTH.countdownLow);
    expect(cueLook('countdown', moving(8)).strength).toBeCloseTo(onBeat, 6);
  });

  it('go starts at full brightness and settles to a steady green', () => {
    expect(cueLook('go', moving(10, 0)).strength).toBe(CUE_STRENGTH.goFlash);
    const settled = cueLook('go', moving(13, 3)).strength;
    expect(settled).toBeCloseTo(CUE_STRENGTH.goSteady, 3);
    expect(cueLook('go', moving(10.2, 0.2)).strength).toBeGreaterThan(settled);
    expect(cueLook('go', moving(10, -1)).strength).toBe(CUE_STRENGTH.goFlash); // clock hiccup
  });

  it('go is clearly brighter than the countdown', () => {
    expect(CUE_STRENGTH.goSteady).toBeGreaterThan(CUE_STRENGTH.countdownSteady);
    expect(CUE_STRENGTH.goFlash).toBeGreaterThan(CUE_STRENGTH.countdownBeat);
  });

  it('reduced motion: steady colours, no pulse and no flash', () => {
    const waits = [0, 0.3, 0.9, 5.5].map((t) => cueLook('countdown', still(t)).strength);
    expect(new Set(waits)).toEqual(new Set([CUE_STRENGTH.countdownSteady]));
    const goes = [0, 0.05, 0.4, 3].map((since) => cueLook('go', still(9, since)).strength);
    expect(new Set(goes)).toEqual(new Set([CUE_STRENGTH.goSteady]));
  });
});

describe('go sound', () => {
  it('is short, quiet and rising', () => {
    expect(GO_SOUND.length).toBeGreaterThan(0);
    expect(soundLengthMs(GO_SOUND)).toBeLessThanOrEqual(300);
    for (const note of GO_SOUND) {
      expect(note.gain).toBeGreaterThan(0);
      expect(note.gain).toBeLessThanOrEqual(0.25);
      expect(note.frequencyHz).toBeGreaterThan(400);
      expect(note.frequencyHz).toBeLessThan(2000);
    }
    expect(GO_SOUND[0]?.atMs).toBe(0); // no delay: reaction time is measured from the signal
    const pitches = GO_SOUND.map((note) => note.frequencyHz);
    expect([...pitches].sort((a, b) => a - b)).toEqual(pitches);
    expect(soundLengthMs([])).toBe(0);
  });
});
