// Procedural robot motions: used when the model has no clip for a name (the stand-in model has
// none; an older alpha_mini.glb lacks the game clips). Each motion is a pure function from
// progress p ∈ [0, 1] to a RobotPose offset from the rest pose. One-shots start and end at rest;
// loops are seamless. This file holds the resting loops and the social gestures; the game motions
// (act_*, duel_*, stare_*, rps_*) are in gameMotions.ts.
import { GAME_MOTIONS } from './gameMotions';
import {
  addPoses,
  bump,
  clamp01,
  hold,
  pose,
  REST,
  scalePose,
  TAU,
  type ProceduralMotion,
  type RobotPose,
} from './robotPose';

export { addPoses, pose, REST, scalePose, type ProceduralMotion, type RobotPose };

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
  // "No idea": shoulders up, forearms out with open hands, head tilted.
  shrug: {
    durationS: 1.5,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.22);
      return pose({
        armLRaise: 0.45 * h,
        armRRaise: 0.45 * h,
        armLForward: 0.15 * h,
        armRForward: 0.15 * h,
        elbowLBend: 1.25 * h,
        elbowRBend: 1.25 * h,
        headRoll: 0.16 * h,
        bodyLift: 0.012 * h,
      });
    },
  },
  // Head and shoulders drop, arms hang, a slow small head shake.
  sad: {
    durationS: 2.4,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.25);
      return pose({
        headPitch: 0.42 * h,
        headYaw: 0.1 * Math.sin(p * TAU * 2) * h,
        bodyBow: 0.1 * h,
        bodyLift: -0.01 * h,
        armLForward: 0.14 * h,
        armRForward: 0.14 * h,
      });
    },
  },
  // A polite bow from the feet: one arm across the chest, the other behind.
  bow: {
    durationS: 2.2,
    loop: false,
    sample: (p) => {
      const h = hold(p, 0.3);
      return pose({
        bodyBow: 0.5 * h,
        headPitch: 0.25 * h,
        armRForward: 0.55 * h,
        armRRaise: -0.25 * h,
        elbowRBend: 1.7 * h,
        armLForward: -0.3 * h,
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
  // act_* (crocodile), duel_* (quick-draw duel), stare_* (staring contest), rps_* (arm rps)
  ...GAME_MOTIONS,
};

export const PROCEDURAL_NAMES: readonly string[] = Object.keys(PROCEDURAL_MOTIONS);

/** The pose of motion `name` at `elapsedS` seconds; loops wrap, one-shots clamp to the end. */
export function sampleMotion(name: string, elapsedS: number): RobotPose {
  const motion = Object.hasOwn(PROCEDURAL_MOTIONS, name) ? PROCEDURAL_MOTIONS[name] : undefined;
  if (!motion) return REST;
  const raw = elapsedS / motion.durationS;
  const p = motion.loop ? raw - Math.floor(raw) : clamp01(raw);
  return motion.sample(p);
}
