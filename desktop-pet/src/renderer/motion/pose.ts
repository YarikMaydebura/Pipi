// A Pose is a set of offsets from the robot's rest pose. Idle life, cursor-following and
// named motions each produce a Pose; they are added together and applied to the 3D rig.
// Angles are radians, lengths are in robot heights (the model is normalised to height 1).

export interface Pose {
  readonly headYaw: number; // + turns toward the viewer's right
  readonly headPitch: number; // + looks down
  readonly headRoll: number; // + tilts toward the viewer's right
  readonly bodyLift: number; // + moves the whole robot up
  readonly bodyLean: number; // + leans toward the viewer's right
  readonly bodyBow: number; // + bows forward (toward the viewer)
  readonly bodyYaw: number; // + turns the whole robot toward the viewer's right (spin)
  readonly squash: number; // + squashes vertically (and widens), - stretches
  readonly armLRaise: number; // robot's left arm (+X): + lifts sideways, away from the body
  readonly armRRaise: number; // robot's right arm (-X)
  readonly armLForward: number; // + swings forward and up
  readonly armRForward: number;
  readonly antennaRoll: number; // + tips toward the viewer's right
  readonly antennaPitch: number; // + tips forward
}

export const ZERO_POSE: Pose = {
  headYaw: 0,
  headPitch: 0,
  headRoll: 0,
  bodyLift: 0,
  bodyLean: 0,
  bodyBow: 0,
  bodyYaw: 0,
  squash: 0,
  armLRaise: 0,
  armRRaise: 0,
  armLForward: 0,
  armRForward: 0,
  antennaRoll: 0,
  antennaPitch: 0,
};

const KEYS = Object.keys(ZERO_POSE) as (keyof Pose)[];

export function pose(partial: Partial<Pose>): Pose {
  return { ...ZERO_POSE, ...partial };
}

export function addPoses(...poses: readonly Pose[]): Pose {
  const sum: Record<keyof Pose, number> = { ...ZERO_POSE };
  for (const p of poses) for (const key of KEYS) sum[key] += p[key];
  return sum;
}

/** Blend from `a` (t = 0) to `b` (t = 1), field by field. */
export function lerpPose(a: Pose, b: Pose, t: number): Pose {
  const out: Record<keyof Pose, number> = { ...ZERO_POSE };
  for (const key of KEYS) out[key] = a[key] + (b[key] - a[key]) * t;
  return out;
}

/** Scale only the movements that travel (lift and squash); used for reduced motion. */
export function dampTravel(p: Pose, factor: number): Pose {
  return { ...p, bodyLift: p.bodyLift * factor, squash: p.squash * factor };
}

/** Frame-rate independent smoothing toward `target` (higher `rate` = faster). */
export function damp(current: number, target: number, rate: number, dt: number): number {
  return target + (current - target) * Math.exp(-rate * dt);
}

/** 0 → 1 → 0 over p ∈ [0,1], holding 1 in the middle (ramps take `edge` of the time). */
export function hold(p: number, edge = 0.2): number {
  if (p <= 0 || p >= 1) return 0;
  const up = Math.min(1, p / edge);
  const down = Math.min(1, (1 - p) / edge);
  const t = Math.min(up, down);
  return t * t * (3 - 2 * t); // smoothstep
}
