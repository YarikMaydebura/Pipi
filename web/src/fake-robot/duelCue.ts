// Quick-draw duel signals (docs/GAMES.md §3.2). The brain only changes the EYES: `countdown`
// (amber) while the participant waits, then `signal_go` (green) = "shout BANG now". On a
// projector the two small eye displays are easy to miss, so the page repeats the eye state as a
// scene cue (tinted light + a glowing ring on the desk + a wall glow) and plays a short "go"
// sound. Everything here is pure (numbers only); RobotScene / overlay / main.ts apply it.
import type { EyeState } from '@pipi/shared';
import type { ToneNote } from '@pipi/shared/body';
import { PALETTES } from '@pipi/shared/look';

export type DuelCue = 'none' | 'countdown' | 'go';

/** The scene cue that belongs to an eye state (only the two duel states have one). */
export function cueForEyes(state: EyeState): DuelCue {
  if (state === 'countdown') return 'countdown';
  if (state === 'signal_go') return 'go';
  return 'none';
}

/** Same amber / green as the eyes, so the room and the eyes read as one signal. */
export const CUE_COLORS: Readonly<Record<Exclude<DuelCue, 'none'>, string>> = {
  countdown: PALETTES.amber.mid,
  go: PALETTES.green.mid,
};

export interface CueLook {
  /** CSS hex colour, or null when no cue is shown. */
  readonly color: string | null;
  /** 0 = nothing, 1 = full brightness. */
  readonly strength: number;
}

export interface CueClock {
  /** The eye clock in seconds (the countdown ring of the eyes drains once per second of it). */
  readonly t: number;
  /** Seconds since this cue started. */
  readonly sinceS: number;
  /** prefers-reduced-motion: steady colours, no pulse, no flash. */
  readonly reducedMotion: boolean;
}

export const CUE_STRENGTH = {
  countdownLow: 0.4, // between beats
  countdownBeat: 0.8, // on each second, in step with the eyes' draining ring
  countdownSteady: 0.6, // reduced motion
  goFlash: 1, // the instant the eyes turn green
  goSteady: 0.72, // what the flash settles to (and reduced motion)
  goDecayPerS: 5,
} as const;

/** How the scene cue looks right now. */
export function cueLook(cue: DuelCue, clock: CueClock): CueLook {
  if (cue === 'none') return { color: null, strength: 0 };
  const s = CUE_STRENGTH;
  if (cue === 'countdown') {
    if (clock.reducedMotion) return { color: CUE_COLORS.countdown, strength: s.countdownSteady };
    const sinceBeat = clock.t - Math.floor(clock.t); // 0 right on the beat
    const beat = (1 - sinceBeat) ** 2;
    return {
      color: CUE_COLORS.countdown,
      strength: s.countdownLow + (s.countdownBeat - s.countdownLow) * beat,
    };
  }
  if (clock.reducedMotion) return { color: CUE_COLORS.go, strength: s.goSteady };
  const flash = Math.exp(-Math.max(0, clock.sinceS) * s.goDecayPerS);
  return { color: CUE_COLORS.go, strength: s.goSteady + (s.goFlash - s.goSteady) * flash };
}

/**
 * The "go" sound: two quick rising notes (A5 → E6), about a quarter of a second, generated with
 * Web Audio oscillators (no file, no network). Quiet on purpose: the brain's bang detector
 * listens for a loudness spike from the participant, not from us.
 */
export const GO_SOUND: readonly ToneNote[] = [
  { frequencyHz: 880, atMs: 0, durationMs: 90, gain: 0.2, wave: 'triangle' },
  { frequencyHz: 1318.5, atMs: 70, durationMs: 190, gain: 0.22, wave: 'triangle' },
];

/** Length of the go sound in ms (for docs and tests). */
export function soundLengthMs(notes: readonly ToneNote[]): number {
  return notes.reduce((end, note) => Math.max(end, note.atMs + note.durationMs), 0);
}
