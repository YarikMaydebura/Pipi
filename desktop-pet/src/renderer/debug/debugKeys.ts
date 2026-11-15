// Dev-only controls so every eye state and motion can be checked by hand.
// Keys (click Pipi first so its window has keyboard focus):
//   1 2 3 4 5 6 7 8 9 0 - =   eye states in protocol order (idle … signal_go)
//   m / M                     next / previous motion
//   c                         cheeks on/off      t   chest pulse on/off
//   o                         cycle the mouth: auto → smile → big_smile → small_o → flat → wavy
//   j                         jump off the screen, come back after 1.5 s (migration test)
//   s                         say a test line (caption + talking animation, no audio)
//   q                         calm mode on/off (study FOCUS: no fidgets, tiny pokes only)
//   v                         love eyes (pink hearts) for 3 s
// Clips (glb clip if the model has it, else the procedural fallback; see CLIP_KEYS):
//   loops, Shift+letter:  I idle  K talk  H think  Z sleep  L listen  D dance
//                         A look_around  G dangle
//   one-shots:            a happy  w signature_wave  [ jump_out  ] jump_in  n nod
//                         x shake_head  p poke  g giggle  r spin  b shy  u surprised
//                         y yawn  d land  e celebrate  l love
// URL params (also work in a production build): ?debug=1  ?eyes=<state>  ?motion=<name>
//   ?fallback=1 shows the 2D fallback instead of the 3D pet;  ?calm=1 starts in calm mode
import { EyeState } from '@pipi/shared';
import { MOTION_NAMES } from '../motion/motions';
import { MOUTH_SHAPES, type MouthShape } from '../mouth/mouthShapes';
import type { PetController } from '../pet/PetController';

export const EYE_STATE_KEYS = '1234567890-=';
export const MOUTH_CYCLE_KEY = 'o';
export const CALM_KEY = 'q';
export const LOVE_EYES_KEY = 'v';
/** Keys used by the other debug controls (CLIP_KEYS must not reuse them). */
export const CONTROL_KEYS: readonly string[] = ['m', 'M', 'c', 't', 'o', 'j', 's', 'q', 'v'];
/** One key per glb clip (partNames.ts GLB_CLIPS): Shift+letter = loops, the rest one-shots. */
export const CLIP_KEYS: Readonly<Record<string, string>> = {
  I: 'idle',
  K: 'talk',
  H: 'think',
  Z: 'sleep',
  L: 'listen',
  D: 'dance',
  A: 'look_around',
  G: 'dangle',
  a: 'happy',
  w: 'signature_wave',
  '[': 'jump_out',
  ']': 'jump_in',
  n: 'nod',
  x: 'shake_head',
  p: 'poke',
  g: 'giggle',
  r: 'spin',
  b: 'shy',
  u: 'surprised',
  y: 'yawn',
  d: 'land',
  e: 'celebrate',
  l: 'love',
};
const LABEL_MS = 1600;
const LOVE_EYES_MS = 3000;
const AWAY_MS = 1500;
const TEST_LINE = 'Hi! I am Pipi. This is how my captions look while I talk.';

let debugIds = 0;
const debugEnvelope = (): { id: string; ts: number } => {
  debugIds += 1;
  return { id: `debug-${debugIds}`, ts: Date.now() };
};

async function jumpOutAndBack(controller: PetController): Promise<void> {
  await controller.handle({ type: 'deactivate', exit: 'jump_out', ...debugEnvelope() });
  await new Promise((resolve) => setTimeout(resolve, AWAY_MS));
  await controller.handle({ type: 'activate', entrance: 'jump_in', ...debugEnvelope() });
}

/** The eye state bound to a key, or undefined. */
export function eyeStateForKey(key: string): EyeState | undefined {
  const index = EYE_STATE_KEYS.indexOf(key);
  return index >= 0 && key.length === 1 ? EyeState.options[index] : undefined;
}

/** The next mouth for the `o` key; null = "auto" (the mouth follows the eye state). */
export function nextMouthOverride(current: MouthShape | null): MouthShape | null {
  if (current === null) return MOUTH_SHAPES[0];
  return MOUTH_SHAPES[MOUTH_SHAPES.indexOf(current) + 1] ?? null;
}

export function isDebugEnabled(search: string, isDev: boolean): boolean {
  return isDev || new URLSearchParams(search).get('debug') === '1';
}

/** ?fallback=1: skip the 3D pet (to check the 2D fallback look). */
export function forceFallbackRequested(search: string): boolean {
  return new URLSearchParams(search).get('fallback') === '1';
}

/** ?calm=1: start in calm mode (as during the study's FOCUS phase). */
export function calmRequested(search: string): boolean {
  return new URLSearchParams(search).get('calm') === '1';
}

/** The clip bound to a key, or undefined. */
export function clipForKey(key: string): string | undefined {
  return Object.hasOwn(CLIP_KEYS, key) ? CLIP_KEYS[key] : undefined;
}

export interface DebugExtras {
  /** Toggle calm mode; returns the new value. */
  readonly toggleCalm?: () => boolean;
}

/** Apply ?eyes= and ?motion= from the URL (invalid values are ignored with a warning). */
export function applyUrlParams(controller: PetController, search: string): void {
  const params = new URLSearchParams(search);
  const eyes = params.get('eyes');
  if (eyes !== null) {
    const parsed = EyeState.safeParse(eyes);
    if (parsed.success) controller.setEyeState(parsed.data);
    else console.warn(`[pipi] ?eyes=${eyes} is not an eye state`);
  }
  const motion = params.get('motion');
  if (motion !== null && !controller.playMotion(motion).ok) {
    console.warn(`[pipi] ?motion=${motion} is not a known motion`);
  }
}

export function installDebugKeys(
  controller: PetController,
  label: HTMLElement | null,
  extras: DebugExtras = {},
): () => void {
  let motionIndex = -1;
  let cheeks = false;
  let chest = false;
  let mouth: MouthShape | null = null;
  let labelTimer: number | undefined;

  const say = (text: string): void => {
    if (!label) return;
    label.textContent = text;
    label.hidden = false;
    window.clearTimeout(labelTimer);
    labelTimer = window.setTimeout(() => {
      label.hidden = true;
    }, LABEL_MS);
  };

  const onKey = (event: KeyboardEvent): void => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const state = eyeStateForKey(event.key);
    if (state) {
      controller.setEyeState(state);
      say(`eyes: ${state}`);
      return;
    }
    const clip = clipForKey(event.key);
    if (clip) {
      const known = controller.playMotion(clip).ok;
      say(known ? `clip: ${clip}` : `clip: ${clip} (unknown!)`);
      return;
    }
    if (event.key === 'm' || event.key === 'M') {
      const step = event.key === 'm' ? 1 : -1;
      motionIndex = (motionIndex + step + MOTION_NAMES.length) % MOTION_NAMES.length;
      const name = MOTION_NAMES[motionIndex] ?? 'hop';
      controller.playMotion(name);
      say(`motion: ${name}`);
    } else if (event.key === 'c') {
      cheeks = !cheeks;
      controller.setCheeks(cheeks);
      say(`cheeks: ${cheeks ? 'on' : 'off'}`);
    } else if (event.key === MOUTH_CYCLE_KEY) {
      mouth = nextMouthOverride(mouth);
      controller.setMouthOverride(mouth);
      say(`mouth: ${mouth ?? 'auto (follows the eyes)'}`);
    } else if (event.key === 'j') {
      say('jump out + back');
      void jumpOutAndBack(controller);
    } else if (event.key === 's') {
      say('speak (caption only)');
      void controller.handle({
        type: 'speak',
        text: TEST_LINE,
        expression: 'happy',
        ...debugEnvelope(),
      });
    } else if (event.key === CALM_KEY && extras.toggleCalm) {
      say(`calm mode: ${extras.toggleCalm() ? 'on' : 'off'}`);
    } else if (event.key === LOVE_EYES_KEY) {
      controller.flashFace({
        eyes: 'love',
        mouth: 'big_smile',
        cheeks: true,
        durationMs: LOVE_EYES_MS,
      });
      say('eyes: love (pet-only)');
    } else if (event.key === 't') {
      chest = !chest;
      controller.setChestPulse(chest);
      say(`chest pulse: ${chest ? 'on' : 'off'}`);
    }
  };

  window.addEventListener('keydown', onKey);
  console.info(
    '[pipi] debug keys: 1-9 0 - = eye states, m/M motions, c cheeks, t chest pulse, o mouth, ' +
      'j jump, s speak, q calm, v love eyes; clips: ' +
      Object.entries(CLIP_KEYS)
        .map(([key, name]) => `${key} ${name}`)
        .join(', '),
  );
  return () => window.removeEventListener('keydown', onKey);
}
