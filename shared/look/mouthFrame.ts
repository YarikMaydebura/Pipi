// Pure mouth model: which mouth Pipi shows for an eye state, and how speech moves it.
// No DOM, no three.js. Design rule: the default face is friendly and happy, never neutral or
// sad, so even "sad" and "determined" keep a kind mouth.
import { clamp, type EyeLook } from './eyeFrame';
import { MOUTH_GLOW, type MouthShape } from './mouthShapes';

/** A drawn mouth shape, or 'off' (screen off: nothing glows). */
export type MouthState = MouthShape | 'off';

export interface MouthFrame {
  readonly shape: MouthState;
  /** Size of the open part: 1 = the shape at rest (big_smile depth, small_o radius). */
  readonly open: number;
  readonly glow: number; // 0..1
}

// Record<EyeLook, ...> makes the compiler fail if a protocol state is ever missing here.
export const MOUTH_FOR_STATE: Readonly<Record<EyeLook, MouthState>> = {
  idle: 'smile',
  blink: 'smile',
  listening: 'smile',
  thinking: 'small_o',
  happy: 'big_smile',
  sad: 'wavy', // nervous rather than sad: still friendly
  surprised: 'small_o',
  determined: 'smile',
  sleepy: 'flat',
  off: 'off',
  countdown: 'smile',
  signal_go: 'big_smile',
  love: 'big_smile',
};

/** Below this speech level Pipi counts as silent (pauses between words close the mouth). */
export const TALK_MIN_LEVEL = 0.08;
const TALK_SMILE_OPEN = { min: 0.35, range: 0.5 } as const; // smile → small open mouth
const TALK_HAPPY_OPEN = { min: 0.6, range: 0.4 } as const; // big smile breathes with the voice
const TALK_O_GROW = 0.25;
const TALK_GLOW = 0.2;

export function mouthForState(state: EyeLook): MouthState {
  return MOUTH_FOR_STATE[state];
}

/** Speech: the resting smile opens with the loudness; other shapes pulse a little. */
function talking(base: MouthShape, level: number): Pick<MouthFrame, 'shape' | 'open'> {
  if (level < TALK_MIN_LEVEL) return { shape: base, open: 1 };
  switch (base) {
    case 'smile':
      return { shape: 'big_smile', open: TALK_SMILE_OPEN.min + TALK_SMILE_OPEN.range * level };
    case 'big_smile':
      return { shape: 'big_smile', open: TALK_HAPPY_OPEN.min + TALK_HAPPY_OPEN.range * level };
    case 'small_o':
      return { shape: 'small_o', open: 1 + TALK_O_GROW * level };
    default:
      return { shape: base, open: 1 };
  }
}

/** The mouth for `base` while the voice is at `speechLevel` (0..1, 0 = silent). */
export function computeMouthFrame(base: MouthState, speechLevel = 0): MouthFrame {
  if (base === 'off') return { shape: 'off', open: 0, glow: 0 };
  const level = clamp(speechLevel, 0, 1);
  return { ...talking(base, level), glow: clamp(MOUTH_GLOW + TALK_GLOW * level, 0, 1) };
}

/** True when two frames would draw the same image (lets the texture skip redraws). */
export function sameMouthFrame(a: MouthFrame | null, b: MouthFrame): boolean {
  return a !== null && a.shape === b.shape && a.open === b.open && a.glow === b.glow;
}
