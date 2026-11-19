// What the showcase plays, in order (pure data; the runner is showcase.ts). It covers every
// clip of pipi.glb and every eye state, so the whole look of Pipi can be shown in about a
// minute and a half. Hold times are the clip lengths in the glb plus a short pause.
import type { EyeState } from '@pipi/shared';

export type ShowcaseStep =
  /** Play a clip with matching eyes; `love` adds the heart eyes (a pet-only face). */
  | {
      readonly kind: 'clip';
      readonly title: string;
      readonly clip: string;
      readonly eyes: EyeState;
      readonly holdMs: number;
      readonly love?: boolean;
    }
  /** Only the eyes change (Pipi stands in its idle loop). */
  | {
      readonly kind: 'eyes';
      readonly title: string;
      readonly eyes: EyeState;
      readonly holdMs: number;
    }
  /** A caption bubble with the talking animation (no sound). */
  | {
      readonly kind: 'speak';
      readonly title: string;
      readonly text: string;
      readonly holdMs: number;
    }
  /** The migration: Pipi hops to the corner, jumps off the screen and comes back. */
  | { readonly kind: 'jump'; readonly title: string };

type ClipStep = Extract<ShowcaseStep, { readonly kind: 'clip' }>;

/** The clips the `jump` step plays (through the migration code). */
export const JUMP_CLIPS: readonly string[] = ['jump_out', 'jump_in'];

const PAUSE_AFTER_ONE_SHOT_MS = 700;
const EYES_HOLD_MS = 1600;

/** A clip that plays once: `clipSeconds` is its length in pipi.glb. */
function oneShot(
  title: string,
  clip: string,
  clipSeconds: number,
  eyes: EyeState = 'happy',
): ClipStep {
  const holdMs = Math.round(clipSeconds * 1000) + PAUSE_AFTER_ONE_SHOT_MS;
  return { kind: 'clip', title, clip, eyes, holdMs };
}

/** A looping clip, shown for `seconds`. */
function loop(title: string, clip: string, seconds: number, eyes: EyeState): ClipStep {
  return { kind: 'clip', title, clip, eyes, holdMs: seconds * 1000 };
}

function eyes(title: string, state: EyeState): ShowcaseStep {
  return { kind: 'eyes', title, eyes: state, holdMs: EYES_HOLD_MS };
}

export const SHOWCASE_STEPS: readonly ShowcaseStep[] = [
  // Hello
  oneShot('signature wave', 'signature_wave', 1.5),
  {
    kind: 'speak',
    title: 'talking with captions',
    text: "Hi, I'm Pipi! Let me show you everything I can do.",
    holdMs: 4500,
  },
  // Feelings
  oneShot('happy', 'happy', 1),
  oneShot('giggle', 'giggle', 1),
  oneShot('celebrate', 'celebrate', 1.5),
  { ...oneShot('love', 'love', 1.5), love: true },
  oneShot('shy', 'shy', 1.5),
  oneShot('surprised', 'surprised', 0.83, 'surprised'),
  // Answers and reactions
  oneShot('nod: yes', 'nod', 0.83),
  oneShot('shake head: no', 'shake_head', 1, 'idle'),
  oneShot('poked', 'poke', 0.83, 'surprised'),
  oneShot('spin', 'spin', 1.25),
  oneShot('yawn', 'yawn', 2, 'sleepy'),
  oneShot('landing', 'land', 0.58),
  // The loops Pipi lives in
  loop('idle', 'idle', 3, 'idle'),
  loop('listening', 'listen', 4, 'listening'),
  loop('thinking', 'think', 4, 'thinking'),
  loop('talking', 'talk', 3, 'happy'),
  loop('looking around', 'look_around', 3, 'idle'),
  loop('dance', 'dance', 4, 'happy'),
  loop('dangling (when dragged)', 'dangle', 2.5, 'surprised'),
  loop('sleeping', 'sleep', 4, 'sleepy'),
  // Eyes that have no clip of their own
  eyes('eyes: sad', 'sad'),
  eyes('eyes: determined', 'determined'),
  eyes('eyes: blink', 'blink'),
  eyes('eyes: duel countdown', 'countdown'),
  eyes('eyes: duel go!', 'signal_go'),
  eyes('eyes: off', 'off'),
  // Finale: the migration
  { kind: 'jump', title: 'jump off the screen' },
];
