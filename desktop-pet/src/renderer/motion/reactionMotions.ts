// Procedural fallbacks for the reaction clips of pipi.glb (poke, giggle, spin, shy, …) and the
// looping "rest" motions (listen, dance, look_around, dangle). They are used whenever the
// model has no clip of that name, so every reaction works with the placeholder robot too.
// One-shots start and end at rest; loops are seamless (sample(0) equals sample(1)) and are
// blended in/out by MotionPlayer.
import type { MotionDef } from './motions';
import { hold, pose, type Pose } from './pose';

const TAU = Math.PI * 2;
const bump = (p: number): number => Math.sin(Math.PI * Math.min(1, Math.max(0, p)));
const easeInOut = (p: number): number =>
  0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, p)));
/** A wobble that dies out: used for the antenna and head after a quick move. */
const wobble = (p: number, cycles: number): number => Math.sin(p * TAU * cycles) * (1 - p);

// --- looping rest motions -------------------------------------------------------------------

function listen(p: number): Pose {
  const s = Math.sin(p * TAU);
  return pose({
    headRoll: 0.13 + 0.02 * s,
    headPitch: 0.04,
    bodyLean: 0.015,
    antennaPitch: 0.12 + 0.04 * s,
  });
}

function thinkLoop(p: number): Pose {
  const s = Math.sin(p * TAU);
  return pose({
    headRoll: 0.22 + 0.03 * s,
    headPitch: -0.12,
    armLForward: 1.2,
    armLRaise: 0.3 + 0.05 * s,
    antennaRoll: 0.06 * s,
  });
}

function sleepLoop(p: number): Pose {
  const breath = Math.sin(p * TAU);
  return pose({
    headPitch: 0.35 + 0.02 * breath,
    bodyBow: 0.1,
    squash: 0.03 + 0.01 * breath,
    antennaPitch: 0.5 + 0.05 * breath,
  });
}

function dance(p: number): Pose {
  const s = Math.sin(p * TAU);
  return pose({
    bodyLean: 0.06 * s,
    bodyLift: 0.035 * Math.abs(Math.sin(p * TAU)),
    headRoll: -0.12 * s,
    armLRaise: 1.2 + 0.6 * s,
    armRRaise: 1.2 - 0.6 * s,
    antennaRoll: 0.25 * Math.sin(p * TAU - 0.8),
  });
}

function lookAround(p: number): Pose {
  return pose({
    headYaw: 0.45 * Math.sin(p * TAU),
    headPitch: -0.05 + 0.04 * Math.sin(p * TAU * 2),
    antennaRoll: -0.1 * Math.sin(p * TAU - 0.6),
  });
}

/** Lifted by the user: stretched, arms out, swinging like a pendulum. */
function dangle(p: number): Pose {
  const swing = Math.sin(p * TAU);
  return pose({
    squash: -0.05,
    bodyLean: 0.08 * swing,
    headRoll: -0.1 * Math.sin(p * TAU - 0.7),
    armLRaise: 0.9 + 0.2 * swing,
    armRRaise: 0.9 - 0.2 * swing,
    antennaRoll: 0.3 * Math.sin(p * TAU - 1.2),
  });
}

// --- one-shot reactions ---------------------------------------------------------------------

/** Poked: a quick squash and lean back, the antenna boings. */
function poke(p: number): Pose {
  const hit = bump(p / 0.35);
  return pose({
    squash: 0.1 * hit,
    headPitch: -0.15 * hit,
    bodyBow: -0.04 * hit,
    antennaPitch: 0.3 * wobble(p, 2.5),
  });
}

/** Giggles: hands to the mouth, little bouncy shakes. */
function giggle(p: number): Pose {
  const h = hold(p, 0.15);
  return pose({
    bodyLift: 0.02 * Math.abs(Math.sin(p * TAU * 6)) * h,
    headRoll: 0.08 * Math.sin(p * TAU * 5) * h,
    armLForward: 0.9 * h,
    armRForward: 0.9 * h,
    armLRaise: 0.2 * h,
    armRRaise: 0.2 * h,
    antennaRoll: 0.2 * Math.sin(p * TAU * 5) * h,
  });
}

/** A full turn on the spot with a little hop; the yaw wraps to 0 at the end (same pose). */
function spin(p: number): Pose {
  const turn = (TAU * easeInOut(p)) % TAU;
  const b = bump(p);
  return pose({
    bodyYaw: p >= 1 ? 0 : turn,
    bodyLift: 0.06 * b,
    armLRaise: 1.0 * b,
    armRRaise: 1.0 * b,
    antennaRoll: 0.25 * b,
  });
}

/** Shy: looks down and away, hands together in front, a small twist. */
function shy(p: number): Pose {
  const h = hold(p, 0.2);
  return pose({
    headPitch: 0.22 * h,
    headRoll: 0.18 * h,
    headYaw: -0.15 * h,
    armLForward: 0.9 * h,
    armRForward: 0.9 * h,
    bodyLean: -0.03 * h,
    bodyYaw: 0.12 * Math.sin(p * TAU * 2) * h,
  });
}

/** Startled: a quick stretch up, arms out, antenna straight back. */
function surprised(p: number): Pose {
  const jolt = bump(p / 0.45);
  const h = hold(p, 0.15);
  return pose({
    squash: -0.08 * jolt,
    bodyLift: 0.04 * jolt,
    armLRaise: 1.1 * h,
    armRRaise: 1.1 * h,
    headPitch: -0.12 * h,
    antennaPitch: -0.3 * h,
  });
}

/** A big stretch with the head back. */
function yawn(p: number): Pose {
  const h = hold(p, 0.3);
  return pose({
    armLRaise: 2.0 * h,
    armRRaise: 2.0 * h,
    headPitch: -0.25 * h,
    squash: -0.04 * h,
    antennaPitch: -0.2 * h,
  });
}

/** Landing after a drag: squash, then the antenna and head settle. */
function land(p: number): Pose {
  const squash = bump(p / 0.4);
  return pose({
    squash: 0.12 * squash,
    armLRaise: 0.6 * squash,
    armRRaise: 0.6 * squash,
    headRoll: 0.08 * wobble(p, 2),
    antennaPitch: -0.3 * wobble(p, 2.5),
  });
}

/** In love: sways happily with hands on the heart. */
function love(p: number): Pose {
  const h = hold(p, 0.2);
  return pose({
    bodyLean: 0.05 * Math.sin(p * TAU * 2) * h,
    headRoll: 0.15 * Math.sin(p * TAU * 2) * h,
    armLForward: 0.6 * h,
    armRForward: 0.6 * h,
    bodyLift: 0.015 * Math.abs(Math.sin(p * TAU * 2)) * h,
    antennaRoll: 0.15 * Math.sin(p * TAU * 2 - 0.5) * h,
  });
}

export const REACTION_MOTIONS: Readonly<Record<string, MotionDef>> = {
  listen: { durationS: 2.4, loop: true, sample: listen },
  think: { durationS: 2.4, loop: true, sample: thinkLoop },
  sleep: { durationS: 3.4, loop: true, sample: sleepLoop },
  dance: { durationS: 1.0, loop: true, sample: dance },
  look_around: { durationS: 4.0, loop: true, sample: lookAround },
  dangle: { durationS: 1.6, loop: true, sample: dangle },
  poke: { durationS: 0.7, sample: poke },
  giggle: { durationS: 1.2, sample: giggle },
  spin: { durationS: 1.1, sample: spin },
  shy: { durationS: 1.8, sample: shy },
  surprised: { durationS: 0.9, sample: surprised },
  yawn: { durationS: 2.2, sample: yawn },
  land: { durationS: 0.6, sample: land },
  love: { durationS: 1.8, sample: love },
};
