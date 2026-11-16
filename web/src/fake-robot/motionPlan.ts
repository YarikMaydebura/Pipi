// Which animation plays for a motion name, and for how long. The brain sends gesture names
// (dialogue `gesture`: nod, shake_head, think, excited, celebrate, shrug, wave, signature_wave),
// game motions (docs/GAMES.md §2: act_*, duel_*, sad, bow) and the body's own clip names
// (wake_up, sleep, dance, ...). Each name maps to an ordered list of candidate clips; the first
// clip the model has wins, otherwise a procedural motion of that name, otherwise the motion is
// unknown (acked with ok: false, like the pet does). Pure, so it is unit-tested.
import { ACT_MOTION_NAMES } from './gameMotions';
import { PROCEDURAL_MOTIONS } from './proceduralMotions';

/** Loops the robot rests in between motions (the brain's eyes / speech pick one). */
export const REST_LOOP_CLIPS = ['idle', 'talk', 'think', 'sleep', 'listen', 'dance'] as const;
/**
 * Motions that keep going until the next motion or a `stop`: the crocodile acting loops (the
 * brain may re-send them while the participant guesses) and the duel's ready stance, which holds
 * until duel_draw / duel_hit / duel_win.
 */
export const HELD_MOTIONS: readonly string[] = [...ACT_MOTION_NAMES, 'duel_ready'];
/** Clips that repeat (LoopRepeat in the mixer). */
export const LOOP_CLIPS: readonly string[] = [...REST_LOOP_CLIPS, ...HELD_MOTIONS];
export const ONE_SHOT_CLIPS = [
  'signature_wave',
  'nod',
  'shake_head',
  'happy',
  'celebrate',
  'wake_up',
  'duel_draw',
  'duel_hit',
  'duel_win',
  'sad',
  'shrug',
  'bow',
] as const;
/** Every clip alpha_mini.glb is expected to contain (docs/SYSTEM_DESIGN.md §6). */
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

/** A resting loop asked for as a gesture (e.g. `think`, `dance`) plays this long, then rests. */
export const LOOP_GESTURE_S = { think: 2.5, dance: 4.5, default: 3 } as const;
/**
 * Safety net for held motions: if the brain never sends the next motion (crash, lost link), the
 * robot stops acting after this long and rests. Far longer than a crocodile round (30 s).
 */
export const HELD_MAX_S = 90;

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

/**
 * How long a motion runs: `once` = plays once and returns to the resting loop; `timed` = a
 * resting loop shown for a few seconds; `held` = repeats / holds until the next motion or stop.
 */
export type MotionMode = 'once' | 'timed' | 'held';

export type MotionPlan =
  | { readonly kind: 'clip'; readonly clip: string; readonly mode: MotionMode }
  | { readonly kind: 'procedural'; readonly name: string; readonly mode: MotionMode }
  | { readonly kind: 'unknown'; readonly name: string };

export function isLoopClip(name: string): boolean {
  return LOOP_CLIPS.includes(name);
}

export function isHeldMotion(name: string): boolean {
  return HELD_MOTIONS.includes(name);
}

export function hasProceduralMotion(name: string): boolean {
  return Object.hasOwn(PROCEDURAL_MOTIONS, name);
}

/** The mode of the clip or procedural motion called `name`. */
export function motionMode(name: string): MotionMode {
  if (isHeldMotion(name)) return 'held';
  const loops = isLoopClip(name) || (hasProceduralMotion(name) && PROCEDURAL_MOTIONS[name]?.loop);
  return loops ? 'timed' : 'once';
}

/** How long a resting loop plays when it was requested as a gesture. */
export function loopGestureSeconds(name: string): number {
  if (name === 'think') return LOOP_GESTURE_S.think;
  if (name === 'dance') return LOOP_GESTURE_S.dance;
  return LOOP_GESTURE_S.default;
}

/** Seconds after which a `timed` / `held` motion ends by itself (not used for `once`). */
export function motionSeconds(name: string, mode: MotionMode): number {
  return mode === 'held' ? HELD_MAX_S : loopGestureSeconds(name);
}

export function motionCandidates(name: string): readonly string[] {
  return Object.hasOwn(MOTION_ALIASES, name) ? (MOTION_ALIASES[name] ?? [name]) : [name];
}

/** Decide how to show motion `name` on a model that has the clips `hasClip` says it has. */
export function planMotion(name: string, hasClip: (clip: string) => boolean): MotionPlan {
  const candidates = motionCandidates(name);
  const clip = candidates.find(hasClip);
  if (clip) return { kind: 'clip', clip, mode: motionMode(clip) };
  const procedural = candidates.find(hasProceduralMotion);
  if (procedural) return { kind: 'procedural', name: procedural, mode: motionMode(procedural) };
  return { kind: 'unknown', name };
}
