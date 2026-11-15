// Pure eye model: turns an EyeState plus time into plain numbers that the drawer paints.
// No DOM, no three.js, so every state can be unit-tested.
//
// Style: Pipi's eyes are glowing warm-teal rounded rectangles with a white highlight, shown on
// a dark face screen. One square image describes ONE eye; see drawEyes.ts for the layout.
import type { EyeState } from '@pipi/shared';

/**
 * Eye looks only the pet uses for its own reactions (not part of the protocol `EyeState`):
 * love = pink heart eyes (assets/pipi3d/eye_images.py "love").
 */
export const PET_EYE_LOOKS = ['love'] as const;
export type PetEyeLook = (typeof PET_EYE_LOOKS)[number];
/** Everything the eyes can show: a protocol state or a pet-only look. */
export type EyeLook = EyeState | PetEyeLook;

/** Colours of the glowing eye, from top (light) to bottom (deep). */
export interface EyePalette {
  readonly light: string;
  readonly mid: string;
  readonly deep: string;
}

export type EyeShape = 'pill' | 'arc' | 'heart' | 'off';

/** A circular ring around the eye (countdown progress, listening pulse, go signal). */
export interface EyeRing {
  readonly progress: number; // 0..1 of the full circle
  readonly radius: number; // relative to the image size
  readonly alpha: number; // 0..1
  readonly color: string;
}

/** Everything needed to paint one eye image for one frame. */
export interface EyeFrame {
  readonly state: EyeLook;
  readonly shape: EyeShape;
  readonly openness: number; // 0 closed .. 1 fully open (blink already applied)
  readonly palette: EyePalette;
  readonly width: number; // relative to the image size
  readonly height: number; // relative to the image size
  readonly gazeX: number; // -1 .. 1, + = toward the image's right
  readonly gazeY: number; // -1 (up) .. 1 (down)
  readonly lidTilt: number; // radians; + = outer corner down (sad), - = inner corner down
  /** 0 = flat bottom; > 0 lifts the bottom edge into an upward curve ("smiling eyes"). */
  readonly smile: number;
  readonly glow: number; // 0..1
  readonly ring: EyeRing | null;
  readonly orbitDots: { readonly phase: number; readonly count: number } | null;
}

export interface EyeFrameInput {
  /** Where Pipi looks, each axis in -1..1 (values outside are clamped). */
  readonly gaze?: { readonly x: number; readonly y: number };
  /** 0 = open, 1 = fully closed. Ignored by states that cannot blink. */
  readonly blink?: number;
}

export const EYE_TEAL = '#3fe0c5';

export const PALETTES = {
  teal: { light: '#b8fff1', mid: EYE_TEAL, deep: '#17a58f' },
  sadTeal: { light: '#bfe9e3', mid: '#5cbcb1', deep: '#2b7c75' },
  brightTeal: { light: '#e4fffa', mid: '#52f2d8', deep: '#10a891' },
  amber: { light: '#fff1c4', mid: '#ffb22e', deep: '#d4600a' },
  green: { light: '#e6ffe9', mid: '#45f27f', deep: '#0d9a3f' },
  heartPink: { light: '#ffd3dc', mid: '#ff7a93', deep: '#e2456a' },
} as const satisfies Record<string, EyePalette>;

/** Static look of each state; time-based motion is added in computeEyeFrame. */
interface EyePreset {
  readonly shape: EyeShape;
  readonly openness: number;
  readonly palette: EyePalette;
  readonly width: number;
  readonly height: number;
  readonly gaze: { readonly x: number; readonly y: number } | null; // null = follow input gaze
  readonly lidTilt: number;
  readonly smile: number;
  readonly glow: number;
  readonly canBlink: boolean;
}

/** Depth of the smiling eyes' bottom curve, relative to the eye height (eye_images.py). */
export const SMILING_EYES = 0.22;

const BASE: EyePreset = {
  shape: 'pill',
  openness: 1,
  palette: PALETTES.teal,
  width: 0.4,
  height: 0.6,
  gaze: null,
  lidTilt: 0,
  smile: 0,
  glow: 0.65,
  canBlink: true,
};

// Record<EyeLook, ...> makes the compiler fail if a protocol state is ever missing here.
export const EYE_PRESETS: Readonly<Record<EyeLook, EyePreset>> = {
  // Resting states smile with their eyes: Pipi's default face is friendly, never neutral.
  idle: { ...BASE, smile: SMILING_EYES },
  blink: { ...BASE, openness: 0, canBlink: false },
  listening: { ...BASE, width: 0.42, height: 0.66, smile: SMILING_EYES, glow: 0.95 },
  thinking: { ...BASE, height: 0.54, gaze: { x: 0.5, y: -0.55 }, glow: 0.55 },
  happy: { ...BASE, shape: 'arc', glow: 0.85, canBlink: false },
  sad: {
    ...BASE,
    openness: 0.66,
    palette: PALETTES.sadTeal,
    gaze: { x: 0, y: 0.5 },
    lidTilt: 0.35,
    glow: 0.4,
  },
  surprised: { ...BASE, width: 0.5, height: 0.7, glow: 0.9 },
  determined: { ...BASE, openness: 0.6, palette: PALETTES.brightTeal, lidTilt: -0.35, glow: 0.9 },
  sleepy: { ...BASE, openness: 0.28, gaze: { x: 0, y: 0.35 }, glow: 0.35 },
  off: { ...BASE, shape: 'off', glow: 0, canBlink: false },
  countdown: { ...BASE, palette: PALETTES.amber, glow: 0.85, canBlink: false },
  signal_go: {
    ...BASE,
    palette: PALETTES.green,
    width: 0.46,
    height: 0.66,
    glow: 1,
    canBlink: false,
  },
  // Pet-only: pink hearts (width = the heart's size), a gentle heartbeat in computeEyeFrame.
  love: { ...BASE, shape: 'heart', palette: PALETTES.heartPink, glow: 0.9, canBlink: false },
};

/** Heartbeat of the love eyes: size change and beats per second. */
export const HEARTBEAT = { amount: 0.06, perSecond: 1.2 } as const;

const TAU = Math.PI * 2;

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** True when the automatic blink may close the eyes in this state. */
export function canAutoBlink(state: EyeLook): boolean {
  return EYE_PRESETS[state].canBlink;
}

/** Ring overlays and small time-based animations that make some states feel alive. */
function stateDetails(state: EyeLook, t: number): Pick<EyeFrame, 'ring' | 'orbitDots'> {
  switch (state) {
    case 'listening': {
      // A soft ring that keeps expanding outward, like sound arriving.
      const phase = (t / 1.4) % 1;
      return {
        ring: {
          progress: 1,
          radius: 0.36 + phase * 0.1,
          alpha: 0.7 * (1 - phase),
          color: '#a8fff0',
        },
        orbitDots: null,
      };
    }
    case 'thinking':
      return { ring: null, orbitDots: { phase: (t * 0.9) % 1, count: 3 } };
    case 'countdown':
      // The ring drains once per second, so each beat of "3, 2, 1" is visible.
      return {
        ring: { progress: 1 - (t % 1), radius: 0.44, alpha: 0.95, color: '#ffcf6b' },
        orbitDots: null,
      };
    case 'signal_go':
      // Gentle 2 Hz pulse: lively, but well below flashing thresholds.
      return {
        ring: {
          progress: 1,
          radius: 0.44,
          alpha: 0.75 + 0.25 * Math.sin(t * TAU * 2),
          color: '#c2ffd2',
        },
        orbitDots: null,
      };
    default:
      return { ring: null, orbitDots: null };
  }
}

/** Compute the frame for `state` at time `t` (seconds). Deterministic for equal inputs. */
export function computeEyeFrame(state: EyeLook, t: number, input: EyeFrameInput = {}): EyeFrame {
  const preset = EYE_PRESETS[state];
  const blink = preset.canBlink ? clamp(input.blink ?? 0, 0, 1) : 0;
  const gaze = preset.gaze ?? input.gaze ?? { x: 0, y: 0 };

  // Tiny "alive" variations: sleepy eyes droop and recover, listening eyes breathe.
  let openness = preset.openness;
  let glow = preset.glow;
  if (state === 'sleepy') openness += 0.08 * Math.sin(t * 0.9);
  if (state === 'listening') glow += 0.05 * Math.sin(t * 3);
  const beat =
    state === 'love' ? 1 + HEARTBEAT.amount * Math.sin(t * TAU * HEARTBEAT.perSecond) : 1;

  return {
    state,
    shape: preset.shape,
    openness: clamp(openness * (1 - blink), 0, 1),
    palette: preset.palette,
    width: preset.width * beat,
    height: preset.height * beat,
    gazeX: clamp(gaze.x, -1, 1),
    gazeY: clamp(gaze.y, -1, 1),
    lidTilt: preset.lidTilt,
    smile: preset.smile,
    glow: clamp(glow, 0, 1),
    ...stateDetails(state, t),
  };
}

/**
 * The frame for the robot's RIGHT eye. Its UVs are mirrored horizontally, so horizontal gaze
 * must be flipped in the image for both eyes to look the same way on screen.
 */
export function mirrorForRightEye(frame: EyeFrame): EyeFrame {
  return { ...frame, gazeX: -frame.gazeX };
}
