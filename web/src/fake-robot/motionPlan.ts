// Which animation plays for a motion name. The brain sends gesture names (dialogue `gesture`:
// nod, shake_head, think, excited, celebrate, shrug, wave, signature_wave) and the body's own
// clip names (wake_up, sleep, dance, ...). Each name maps to an ordered list of candidate clips;
// the first clip the model has wins, otherwise a procedural motion of that name, otherwise the
// motion is unknown (acked with ok: false, like the pet does). Pure, so it is unit-tested.
import { PROCEDURAL_MOTIONS } from './proceduralMotions';

/** Clips alpha_mini.glb provides (docs/SYSTEM_DESIGN.md §6). */
export const LOOP_CLIPS = ['idle', 'talk', 'think', 'sleep', 'listen', 'dance'] as const;
export const ONE_SHOT_CLIPS = [
  'signature_wave',
  'nod',
  'shake_head',
  'happy',
  'celebrate',
  'wake_up',
] as const;
export const ROBOT_CLIPS: readonly string[] = [...LOOP_CLIPS, ...ONE_SHOT_CLIPS];

/** Loops the robot rests in between one-shots. */
export type BaseLoop = 'idle' | 'talk' | 'listen' | 'think' | 'sleep';

/** Crossfade into a base loop: slow into the sleep slump, quick otherwise. */
export const SLEEP_FADE_S = 1.4;
export const BASE_FADE_S = 0.35;
export const ONE_SHOT_FADE_S = 0.25;

export function baseFadeSeconds(loop: BaseLoop): number {
  return loop === 'sleep' ? SLEEP_FADE_S : BASE_FADE_S;
}

/** A looping clip asked for as a gesture (e.g. `think`, `dance`) plays this long, then rests. */
export const LOOP_GESTURE_S = { think: 2.5, dance: 4.5, default: 3 } as const;

/** Gesture names that are spelled differently from the clip, in order of preference. */
export const MOTION_ALIASES: Readonly<Record<string, readonly string[]>> = {
  wave: ['signature_wave'],
  excited: ['happy', 'celebrate'],
  happy: ['happy', 'celebrate'],
  celebrate: ['celebrate', 'happy'],
  yes: ['nod'],
  no: ['shake_head'],
  thinking: ['think'],
  listening: ['listen'],
  jump_in: ['wake_up'], // the robot has no jump: an entrance is a wake-up
};

export type MotionPlan =
  | { readonly kind: 'clip'; readonly clip: string; readonly loop: boolean }
  | { readonly kind: 'procedural'; readonly name: string }
  | { readonly kind: 'unknown'; readonly name: string };

export function isLoopClip(name: string): boolean {
  return (LOOP_CLIPS as readonly string[]).includes(name);
}

/** How long a loop clip plays when it was requested as a gesture. */
export function loopGestureSeconds(name: string): number {
  if (name === 'think') return LOOP_GESTURE_S.think;
  if (name === 'dance') return LOOP_GESTURE_S.dance;
  return LOOP_GESTURE_S.default;
}

export function motionCandidates(name: string): readonly string[] {
  return MOTION_ALIASES[name] ?? [name];
}

/** Decide how to show motion `name` on a model that has the clips `hasClip` says it has. */
export function planMotion(name: string, hasClip: (clip: string) => boolean): MotionPlan {
  const candidates = motionCandidates(name);
  const clip = candidates.find(hasClip);
  if (clip) return { kind: 'clip', clip, loop: isLoopClip(clip) };
  const procedural = candidates.find((candidate) => candidate in PROCEDURAL_MOTIONS);
  if (procedural) return { kind: 'procedural', name: procedural };
  return { kind: 'unknown', name };
}
