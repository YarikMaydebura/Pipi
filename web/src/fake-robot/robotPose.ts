// A RobotPose is a set of offsets from the robot's rest pose (arms hanging, looking ahead).
// Procedural motions produce poses; the rig (scene/rig.ts) applies them on top of the clips.
// Angles in radians, lengths in robot heights (the model is normalised to height 1).

export interface RobotPose {
  readonly headYaw: number; // + turns toward the viewer's right
  readonly headPitch: number; // + looks down
  readonly headRoll: number; // + tilts toward the viewer's right
  readonly bodyLift: number; // + moves the whole robot up
  readonly bodyLean: number; // + leans toward the viewer's right
  readonly bodyBow: number; // + bows forward, - leans back
  readonly bodyYaw: number; // + turns the whole robot toward the viewer's right
  readonly armLRaise: number; // robot's left arm (+X): + lifts sideways, - crosses the body
  readonly armRRaise: number; // robot's right arm (-X)
  readonly armLForward: number; // + swings forward and up (π/2 = pointing ahead, π = overhead)
  readonly armRForward: number;
  readonly elbowLBend: number; // + bends the forearm toward the front of the upper arm
  readonly elbowRBend: number;
}

export const REST: RobotPose = {
  headYaw: 0,
  headPitch: 0,
  headRoll: 0,
  bodyLift: 0,
  bodyLean: 0,
  bodyBow: 0,
  bodyYaw: 0,
  armLRaise: 0,
  armRRaise: 0,
  armLForward: 0,
  armRForward: 0,
  elbowLBend: 0,
  elbowRBend: 0,
};

export function pose(values: Partial<RobotPose>): RobotPose {
  return { ...REST, ...values };
}

const KEYS = Object.keys(REST) as (keyof RobotPose)[];

export function addPoses(a: RobotPose, b: RobotPose): RobotPose {
  const out: Record<keyof RobotPose, number> = { ...a };
  for (const key of KEYS) out[key] = a[key] + b[key];
  return out;
}

export function scalePose(p: RobotPose, factor: number): RobotPose {
  const out: Record<keyof RobotPose, number> = { ...p };
  for (const key of KEYS) out[key] = p[key] * factor;
  return out;
}

/** Blend from `a` (t = 0) to `b` (t = 1), field by field. */
export function mixPoses(a: RobotPose, b: RobotPose, t: number): RobotPose {
  const out: Record<keyof RobotPose, number> = { ...a };
  for (const key of KEYS) out[key] = a[key] + (b[key] - a[key]) * t;
  return out;
}

export interface ProceduralMotion {
  readonly durationS: number;
  /** Loops are seamless (sample(0) equals sample(1)); one-shots start and end at rest. */
  readonly loop: boolean;
  /** Seconds to blend in (default: a soft 0.3 s); short for motions that must snap, e.g. a draw. */
  readonly attackS?: number;
  readonly sample: (p: number) => RobotPose;
}

// --- small shaping helpers shared by the motion files ---------------------------------------

export const TAU = Math.PI * 2;
export const clamp01 = (p: number): number => Math.min(1, Math.max(0, p));
export const smoothstep = (t: number): number => {
  const q = clamp01(t);
  return q * q * (3 - 2 * q);
};
/** 0 → 1 → 0 over p ∈ [0, 1]. */
export const bump = (p: number): number => Math.sin(Math.PI * clamp01(p));
/** Eases in over `edge`, holds at 1, eases out over the last `edge`. */
export function hold(p: number, edge: number): number {
  const q = clamp01(p);
  if (q < edge) return Math.sin((q / edge) * (Math.PI / 2));
  if (q > 1 - edge) return Math.sin(((1 - q) / edge) * (Math.PI / 2));
  return 1;
}
/** sin with `cycles` whole periods over p ∈ [0, 1] (whole numbers keep loops seamless). */
export const wave = (p: number, cycles = 1, phase = 0): number =>
  Math.sin(p * TAU * cycles + phase);
/**
 * A periodic pulse: 1 at `center`, 0 further than `width` away (p wraps around, so a loop that
 * uses it stays seamless).
 */
export function pulse(p: number, center: number, width: number): number {
  const offset = p - center;
  const distance = Math.abs(offset - Math.round(offset)); // on the loop, 0 .. 0.5
  return distance >= width ? 0 : 0.5 + 0.5 * Math.cos((Math.PI * distance) / width);
}

export type Keyframe = readonly [at: number, pose: RobotPose];

/** Smoothly interpolate through keyframes sorted by time (p before/after the ends clamps). */
export function throughKeys(p: number, keys: readonly Keyframe[]): RobotPose {
  const first = keys[0];
  if (!first) return REST;
  let previous = first;
  for (const key of keys) {
    if (p <= key[0]) {
      const span = key[0] - previous[0];
      return span <= 0
        ? key[1]
        : mixPoses(previous[1], key[1], smoothstep((p - previous[0]) / span));
    }
    previous = key;
  }
  return previous[1];
}
