// Procedural named motions. They are used when the model has no animation clip with that
// name (always true for the placeholder). Names follow docs/GAMES.md §2 and the glb clip
// names, so the brain can send the same `motion` message to every body.
// Each motion is a pure function from progress p ∈ [0,1] to a Pose offset. One-shots start and
// end at rest; loops (talk, listen, think, sleep, dance, look_around, dangle) are seamless.
import { REACTION_MOTIONS } from './reactionMotions';
import { hold, lerpPose, pose, ZERO_POSE, type Pose } from './pose';

export interface MotionDef {
  readonly durationS: number;
  readonly loop?: boolean; // loops until another motion (or "idle") replaces it
  readonly sample: (p: number) => Pose;
}

const TAU = Math.PI * 2;
const bump = (p: number): number => Math.sin(Math.PI * Math.min(1, Math.max(0, p)));

function hop(p: number, height = 0.12): Pose {
  // Crouch (squash), jump (stretch + lift), land (squash); the antenna lags behind.
  if (p < 0.2) return pose({ squash: 0.08 * bump(p / 0.2), antennaPitch: -0.2 * bump(p / 0.2) });
  if (p < 0.75) {
    const q = (p - 0.2) / 0.55;
    return pose({
      bodyLift: height * bump(q),
      squash: -0.06 * bump(q),
      antennaPitch: 0.3 * bump(q),
    });
  }
  const q = (p - 0.75) / 0.25;
  return pose({ squash: 0.07 * bump(q), antennaPitch: -0.25 * bump(q) });
}

function wave(p: number): Pose {
  const h = hold(p, 0.18);
  return pose({
    armRRaise: (2.3 + 0.35 * Math.sin(p * TAU * 3)) * h,
    headRoll: -0.12 * h,
    bodyLean: -0.03 * h,
    antennaRoll: 0.15 * Math.sin(p * TAU * 3) * h,
  });
}

function excited(p: number): Pose {
  const h = hold(p, 0.15);
  const wiggle = 0.25 * Math.sin(p * TAU * 4);
  return pose({
    bodyLift: 0.05 * Math.abs(Math.sin(p * TAU * 3)),
    armLRaise: (0.8 + wiggle) * h,
    armRRaise: (0.8 - wiggle) * h,
    antennaRoll: 0.2 * Math.sin(p * TAU * 4) * h,
  });
}

/** Migration out: crouch (squash), then a big stretched leap; the window/CSS carries Pipi away. */
function jumpOut(p: number): Pose {
  const crouchEnd = 0.22;
  if (p < crouchEnd) {
    const c = Math.sin((p / crouchEnd) * (Math.PI / 2));
    return pose({ squash: 0.11 * c, antennaPitch: -0.3 * c, headPitch: 0.08 * c });
  }
  const q = (p - crouchEnd) / (1 - crouchEnd);
  const stretch = bump(Math.min(1, q * 1.4));
  return pose({
    squash: -0.09 * stretch,
    bodyLift: 0.14 * Math.sin(Math.PI * Math.min(1, q * 1.2)),
    armLRaise: 2.2 * hold(q, 0.12),
    armRRaise: 2.2 * hold(q, 0.12),
    headPitch: -0.2 * stretch,
    antennaPitch: 0.45 * stretch,
  });
}

/** Migration in: falls in stretched, lands with a squash, shakes itself off. */
function jumpIn(p: number): Pose {
  if (p < 0.4) {
    const q = p / 0.4;
    const r = Math.min(1, p / 0.06); // ease in from rest (Pipi is still outside the window here)
    return pose({
      squash: -0.07 * (1 - q) * r,
      armLRaise: 1.8 * (1 - q * 0.6) * r,
      armRRaise: 1.8 * (1 - q * 0.6) * r,
      antennaPitch: -0.3 * (1 - q) * r,
    });
  }
  if (p < 0.6) {
    const b = bump((p - 0.4) / 0.2);
    return pose({ squash: 0.12 * b, armLRaise: 0.7 * (1 - b), armRRaise: 0.7 * (1 - b) });
  }
  const q = (p - 0.6) / 0.4;
  const decay = 1 - q;
  return pose({
    headRoll: 0.16 * Math.sin(q * TAU * 3) * decay,
    bodyLean: 0.03 * Math.sin(q * TAU * 3 + 0.6) * decay,
    antennaRoll: 0.3 * Math.sin(q * TAU * 3 - 0.8) * decay,
  });
}

export const MOTIONS: Readonly<Record<string, MotionDef>> = {
  hop: { durationS: 0.7, sample: (p) => hop(p) },
  nod: {
    durationS: 0.9,
    sample: (p) => pose({ headPitch: 0.25 * (0.5 - 0.5 * Math.cos(p * TAU * 2)) }),
  },
  shake_head: {
    durationS: 1.0,
    sample: (p) => pose({ headYaw: 0.35 * Math.sin(p * TAU * 2) * bump(p) }),
  },
  wave: { durationS: 1.8, sample: wave },
  signature_wave: {
    durationS: 2.4,
    sample: (p) => (p < 0.7 ? wave(p / 0.7) : hop((p - 0.7) / 0.3, 0.08)),
  },
  talk: {
    durationS: 1.1,
    loop: true,
    sample: (p) =>
      pose({
        headPitch: 0.05 * Math.sin(p * TAU * 2),
        headRoll: 0.04 * Math.sin(p * TAU),
        bodyLift: 0.006 * Math.abs(Math.sin(p * TAU * 2)),
      }),
  },
  happy: { durationS: 1.2, sample: excited },
  excited: { durationS: 1.2, sample: excited },
  celebrate: {
    durationS: 1.6,
    sample: (p) => {
      const h = hold(p, 0.15);
      return pose({
        bodyLift: 0.08 * Math.abs(Math.sin(p * TAU * 2)),
        armLRaise: 2.4 * h,
        armRRaise: 2.4 * h,
        headPitch: -0.15 * h,
        antennaPitch: 0.2 * Math.sin(p * TAU * 2) * h,
      });
    },
  },
  sad: {
    durationS: 1.8,
    sample: (p) => {
      const h = hold(p);
      return pose({
        headPitch: 0.3 * h,
        bodyBow: 0.08 * h,
        squash: 0.02 * h,
        antennaPitch: 0.4 * h,
      });
    },
  },
  shrug: {
    durationS: 1.0,
    sample: (p) => {
      const b = bump(p);
      return pose({
        armLRaise: 0.6 * b,
        armRRaise: 0.6 * b,
        headRoll: 0.15 * b,
        bodyLift: 0.015 * b,
      });
    },
  },
  bow: {
    durationS: 1.6,
    sample: (p) => {
      const h = hold(p);
      return pose({ bodyBow: 0.4 * h, headPitch: 0.2 * h });
    },
  },
  jump_out: { durationS: 1.0, sample: jumpOut },
  jump_in: { durationS: 1.4, sample: jumpIn },
  wake_up: {
    durationS: 1.8,
    sample: (p) => {
      const h = hold(p, 0.3);
      return pose({
        armLRaise: 2.4 * h,
        armRRaise: 2.4 * h,
        headPitch: -0.25 * h,
        squash: -0.03 * h,
      });
    },
  },
  // listen, think, sleep, dance, look_around, dangle (loops) and the reaction one-shots
  ...REACTION_MOTIONS,
};

export function isKnownMotion(name: string): boolean {
  return Object.hasOwn(MOTIONS, name);
}

/** True for motions that repeat until replaced (they can be a "base" loop). */
export function isLoopMotion(name: string): boolean {
  return isKnownMotion(name) && MOTIONS[name]?.loop === true;
}

export const MOTION_NAMES: readonly string[] = Object.keys(MOTIONS);

/** Blend time when one motion replaces another, so poses never snap. */
export const MOTION_BLEND_S = 0.2;

interface Running {
  readonly def: MotionDef;
  readonly start: number;
}

const smoothstep = (t: number): number => t * t * (3 - 2 * t);

/**
 * Plays named motions in two layers: a looping BASE (what Pipi rests in: nothing = the idle
 * pose, or talk, listen, sleep, dangle, …) and a CURRENT motion on top of it (a one-shot, or a
 * loop that runs until replaced). When a one-shot ends Pipi returns to the base. Every switch
 * is blended over MOTION_BLEND_S.
 */
export class MotionPlayer {
  private current: Running | null = null;
  private base: Running | null = null;
  private blendFrom: Pose | null = null;
  private blendStart = 0;

  /** "idle" stops the current motion. Returns false (and plays nothing) for unknown names. */
  play(name: string, now: number): boolean {
    if (name === 'idle') {
      this.stop(now);
      return true;
    }
    const def = isKnownMotion(name) ? MOTIONS[name] : undefined;
    if (!def) return false;
    this.startBlend(now);
    this.current = { def, start: now };
    return true;
  }

  /**
   * Set the loop to rest in ("idle" = none). With `interrupt`, or when nothing / a loop is
   * playing, the base shows right away; otherwise the running one-shot finishes first.
   * Returns false for names that are not loops.
   */
  setBase(name: string, now: number, interrupt: boolean): boolean {
    const def = name === 'idle' ? null : isLoopMotion(name) ? MOTIONS[name] : undefined;
    if (def === undefined) return false;
    if (this.base?.def === def && !interrupt) return true;
    const oneShotRunning = this.current !== null && this.current.def.loop !== true;
    if (interrupt || !oneShotRunning) {
      this.startBlend(now);
      this.current = null;
    }
    this.base = def ? { def, start: now } : null;
    return true;
  }

  /** Stop the current motion (back to the base loop). */
  stop(now?: number): void {
    if (now !== undefined) this.startBlend(now);
    this.current = null;
  }

  isPlaying(now: number): boolean {
    if (!this.current) return false;
    return this.current.def.loop === true || now - this.current.start < this.current.def.durationS;
  }

  sample(now: number): Pose {
    const raw = this.sampleRaw(now);
    if (!this.blendFrom) return raw;
    const t = (now - this.blendStart) / MOTION_BLEND_S;
    if (t >= 1 || t < 0) {
      this.blendFrom = null;
      return raw;
    }
    return lerpPose(this.blendFrom, raw, smoothstep(t));
  }

  private startBlend(now: number): void {
    this.blendFrom = this.sampleRaw(now);
    this.blendStart = now;
  }

  private sampleRaw(now: number): Pose {
    const current = this.current;
    if (current) {
      const raw = Math.max(0, now - current.start) / current.def.durationS;
      if (current.def.loop) return current.def.sample(raw % 1);
      if (raw < 1) return current.def.sample(raw);
      // The one-shot just ended (at rest): blend from there into the base loop.
      this.current = null;
      if (this.base) {
        this.blendFrom = current.def.sample(1);
        this.blendStart = now;
      }
    }
    if (!this.base) return ZERO_POSE;
    const { def, start } = this.base;
    return def.sample((Math.max(0, now - start) / def.durationS) % 1);
  }
}
