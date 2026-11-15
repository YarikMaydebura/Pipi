// Procedural robot motions: used when the model has no clip for a name (the stand-in model has
// none; alpha_mini.glb lacks e.g. `shrug`). Each motion is a pure function from progress
// p ∈ [0, 1] to a RobotPose offset from the rest pose. One-shots start and end at rest; loops are
// seamless. Angles in radians, lengths in robot heights (the model is normalised to height 1).

export interface RobotPose {
  readonly headYaw: number; // + turns toward the viewer's right
  readonly headPitch: number; // + looks down
  readonly headRoll: number; // + tilts toward the viewer's right
  readonly bodyLift: number; // + moves the whole robot up
  readonly bodyLean: number; // + leans toward the viewer's right
  readonly bodyBow: number; // + bows forward
  readonly armLRaise: number; // robot's left arm (+X): + lifts sideways
  readonly armRRaise: number; // robot's right arm (-X)
  readonly armLForward: number; // + swings forward and up
  readonly armRForward: number;
}

export const REST: RobotPose = {
  headYaw: 0,
  headPitch: 0,
  headRoll: 0,
  bodyLift: 0,
  bodyLean: 0,
  bodyBow: 0,
  armLRaise: 0,
  armRRaise: 0,
  armLForward: 0,
  armRForward: 0,
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

export interface ProceduralMotion {
  readonly durationS: number;
  readonly loop: boolean;
  readonly sample: (p: number) => RobotPose;
}

const TAU = Math.PI * 2;
const clamp01 = (p: number): number => Math.min(1, Math.max(0, p));
/** 0 → 1 → 0 over p ∈ [0, 1]. */
const bump = (p: number): number => Math.sin(Math.PI * clamp01(p));
/** Eases in over `edge`, holds at 1, eases out over the last `edge`. */
function hold(p: number, edge: number): number {
  const q = clamp01(p);
  if (q < edge) return Math.sin((q / edge) * (Math.PI / 2));
  if (q > 1 - edge) return Math.sin(((1 - q) / edge) * (Math.PI / 2));
  return 1;
}

/** Slumped sleep pose (head down, body bowed, arms hanging forward). */
const SLUMP = pose({
  headPitch: 0.45,
  bodyBow: 0.12,
  bodyLift: -0.015,
  armLForward: 0.15,
  armRForward: 0.15,
});

export const PROCEDURAL_MOTIONS: Readonly<Record<string, ProceduralMotion>> = {
  idle: {
    durationS: 4,
    loop: true,
    sample: (p) =>
      pose({ bodyLift: 0.004 * Math.sin(p * TAU), headRoll: 0.03 * Math.sin(p * TAU + 1) }),
  },
  talk: {
    durationS: 1.6,
    loop: true,
    sample: (p) =>
      pose({
        headPitch: 0.05 * Math.sin(p * TAU * 2),
        headYaw: 0.06 * Math.sin(p * TAU),
        armRForward: 0.25 + 0.12 * Math.sin(p * TAU),
      }),
  },
  listen: {
    durationS: 3,
    loop: true,
    sample: (p) => pose({ headRoll: 0.14 + 0.02 * Math.sin(p * TAU), headPitch: -0.04 }),
  },
  think: {
    durationS: 3,
    loop: true,
    sample: (p) =>
      pose({
        headPitch: -0.14,
        headRoll: -0.1 + 0.03 * Math.sin(p * TAU),
        armRForward: 1.2,
        armRRaise: 0.25,
      }),
  },
  sleep: {
    durationS: 4,
    loop: true,
    sample: (p) => addPoses(SLUMP, pose({ bodyLift: 0.004 * Math.sin(p * TAU) })),
  },
  dance: {
    durationS: 1.2,
    loop: true,
    sample: (p) =>
      pose({
        bodyLift: 0.02 * Math.abs(Math.sin(p * TAU)),
        bodyLean: 0.08 * Math.sin(p * TAU),
        headRoll: -0.12 * Math.sin(p * TAU),
        armLRaise: 1.1 + 0.4 * Math.sin(p * TAU),
        armRRaise: 1.1 - 0.4 * Math.sin(p * TAU),
      }),
  },
  nod: {
    durationS: 1.1,
    loop: false,
    sample: (p) => pose({ headPitch: 0.28 * Math.sin(p * TAU * 2) * hold(p, 0.2) }),
  },
  shake_head: {
    durationS: 1.2,
    loop: false,
    sample: (p) => pose({ headYaw: 0.35 * Math.sin(p * TAU * 2.5) * hold(p, 0.15) }),
  },
  signature_wave: {
    durationS: 2,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.18);
      return pose({
        armRRaise: (2.4 + 0.35 * Math.sin(p * TAU * 3)) * h,
        headRoll: -0.12 * h,
        bodyLean: -0.04 * h,
      });
    },
  },
  happy: {
    durationS: 1.3,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.15);
      return pose({
        bodyLift: 0.03 * Math.abs(Math.sin(p * TAU * 2)),
        armLRaise: (0.9 + 0.2 * Math.sin(p * TAU * 4)) * h,
        armRRaise: (0.9 - 0.2 * Math.sin(p * TAU * 4)) * h,
        headPitch: -0.1 * h,
      });
    },
  },
  celebrate: {
    durationS: 1.8,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.12);
      return pose({
        bodyLift: 0.05 * bump(p * 2) + 0.05 * bump(p * 2 - 1),
        armLRaise: 2.6 * h,
        armRRaise: 2.6 * h,
        headPitch: -0.2 * h,
      });
    },
  },
  shrug: {
    durationS: 1.3,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.25);
      return pose({
        armLRaise: 0.5 * h,
        armRRaise: 0.5 * h,
        armLForward: 0.5 * h,
        armRForward: 0.5 * h,
        headRoll: 0.15 * h,
      });
    },
  },
  // Starts in the sleep slump and ends at rest: a stretch, a look around, settle.
  wake_up: {
    durationS: 1.7,
    loop: false,
    sample: (p) => {
      const rise = clamp01(p / 0.45);
      const ease = rise * rise * (3 - 2 * rise);
      const stretch = bump((p - 0.3) / 0.45);
      return addPoses(
        scalePose(SLUMP, 1 - ease),
        pose({
          armLRaise: 1.4 * stretch,
          armRRaise: 1.4 * stretch,
          headPitch: -0.12 * stretch,
          headYaw: 0.25 * Math.sin(clamp01((p - 0.65) / 0.35) * TAU) * (1 - p),
        }),
      );
    },
  },
};

export const PROCEDURAL_NAMES: readonly string[] = Object.keys(PROCEDURAL_MOTIONS);

/** The pose of motion `name` at `elapsedS` seconds; loops wrap, one-shots clamp to the end. */
export function sampleMotion(name: string, elapsedS: number): RobotPose {
  const motion = PROCEDURAL_MOTIONS[name];
  if (!motion) return REST;
  const raw = elapsedS / motion.durationS;
  const p = motion.loop ? raw - Math.floor(raw) : clamp01(raw);
  return motion.sample(p);
}
