// Procedural versions of the game motions (docs/GAMES.md §2), used whenever alpha_mini.glb has no
// clip of that name. Crocodile: the robot acts a word out WITHOUT speaking, so every act_* must be
// recognisable on its own from across a room — big, simple, repeated shapes. Quick-draw duel:
// duel_ready is a tense stance that holds; the draw is fast; the hit is a dramatic slump.
// act_* and duel_ready are seamless loops (they repeat until the next motion); the others are
// one-shots that start and end at rest.
import {
  bump,
  hold,
  pose,
  pulse,
  REST,
  smoothstep,
  throughKeys,
  wave,
  type Keyframe,
  type ProceduralMotion,
  type RobotPose,
} from './robotPose';

const HALF_PI = Math.PI / 2;

// --- crocodile: acting loops ----------------------------------------------------------------

/** Wings: both arms out to the sides, flapping; the body rises as the wings push down. */
function bird(p: number): RobotPose {
  const flap = wave(p, 2);
  return pose({
    armLRaise: 1.3 + 0.75 * flap,
    armRRaise: 1.3 + 0.75 * flap,
    elbowLBend: 0.3 - 0.25 * flap,
    elbowRBend: 0.3 - 0.25 * flap,
    bodyLift: 0.012 - 0.012 * flap,
    bodyBow: 0.1,
    headPitch: -0.12,
    headYaw: 0.22 * wave(p), // a bird looking around
  });
}

/** Guard up (fists at the chin), then a straight left, then a straight right, bouncing. */
function boxer(p: number): RobotPose {
  const left = pulse(p, 0.25, 0.17);
  const right = pulse(p, 0.75, 0.17);
  const twist = 0.3 * (right - left); // the punching shoulder comes forward
  return pose({
    armLForward: 0.95 + 0.6 * left,
    armRForward: 0.95 + 0.6 * right,
    armLRaise: -0.12,
    armRRaise: -0.12,
    elbowLBend: 2.0 - 1.85 * left,
    elbowRBend: 2.0 - 1.85 * right,
    bodyYaw: twist,
    headYaw: -0.8 * twist, // eyes stay on the opponent
    headPitch: 0.08,
    bodyBow: 0.06,
    bodyLift: 0.01 * Math.abs(wave(p, 2)),
  });
}

/** Front crawl: leaning forward, the arms windmill in turn, the head turns to breathe. */
function swimmer(p: number): RobotPose {
  const left = wave(p);
  const right = wave(p, 1, Math.PI);
  return pose({
    armLForward: 1.55 + 1.35 * left,
    armRForward: 1.55 + 1.35 * right,
    armLRaise: 0.3 + 0.3 * wave(p, 1, HALF_PI),
    armRRaise: 0.3 + 0.3 * wave(p, 1, HALF_PI + Math.PI),
    elbowLBend: 0.5 + 0.4 * wave(p, 1, HALF_PI),
    elbowRBend: 0.5 + 0.4 * wave(p, 1, HALF_PI + Math.PI),
    bodyBow: 0.32,
    bodyYaw: 0.16 * left,
    bodyLean: 0.04 * left,
    headPitch: -0.22,
    headYaw: 0.38 * left,
  });
}

/** Ballet: arms in a ring overhead opening to the sides, rising on tiptoe, twirling. */
function dancer(p: number): RobotPose {
  const open = 0.5 + 0.5 * wave(p, 2, HALF_PI); // 1 = arms overhead, 0 = arms out
  return pose({
    armLRaise: 1.55 + 0.85 * open,
    armRRaise: 1.55 + 0.85 * open,
    elbowLBend: 0.25 + 0.55 * open,
    elbowRBend: 0.25 + 0.55 * open,
    bodyYaw: 0.85 * wave(p),
    bodyLift: 0.025 * open,
    bodyLean: 0.05 * wave(p, 2),
    headRoll: 0.14 * wave(p),
    headPitch: -0.1 * open,
  });
}

/** "The robot" dance: stiff right angles that snap from one pose to the next and freeze. */
const ROBOT_STEPS: readonly RobotPose[] = [
  pose({ elbowRBend: HALF_PI, headYaw: -0.45 }),
  pose({ armRForward: HALF_PI, elbowRBend: HALF_PI, elbowLBend: HALF_PI, bodyYaw: 0.25 }),
  pose({ elbowLBend: HALF_PI, armRRaise: HALF_PI, headYaw: 0.45 }),
  pose({ armLForward: HALF_PI, elbowLBend: HALF_PI, armRRaise: HALF_PI, bodyYaw: -0.25 }),
];
const ROBOT_SNAP = 0.22; // share of each step spent moving; the rest is a mechanical freeze

function robotDance(p: number): RobotPose {
  const scaled = (p % 1) * ROBOT_STEPS.length;
  const index = Math.floor(scaled) % ROBOT_STEPS.length;
  const from = ROBOT_STEPS[(index + ROBOT_STEPS.length - 1) % ROBOT_STEPS.length] ?? REST;
  const to = ROBOT_STEPS[index] ?? REST;
  const t = Math.min(1, (scaled - Math.floor(scaled)) / ROBOT_SNAP);
  return throughKeys(t, [
    [0, from],
    [1, to],
  ]);
}

/** Head resting on both hands at one side, slow breathing. */
function sleeping(p: number): RobotPose {
  const breath = wave(p);
  return pose({
    headRoll: 0.4 + 0.02 * breath,
    headPitch: 0.12,
    bodyLean: 0.06,
    bodyLift: 0.005 * breath,
    armLForward: 1.2,
    armLRaise: -0.15,
    elbowLBend: 2.2 + 0.03 * breath,
    armRForward: 1.25,
    armRRaise: -0.7,
    elbowRBend: 1.9 + 0.03 * breath,
  });
}

/** Flying: one fist stretched up and ahead, the other on the hip, chest out, banking. */
function superhero(p: number): RobotPose {
  const sway = wave(p);
  return pose({
    armRForward: 2.75,
    armRRaise: 0.1,
    armLRaise: 0.55,
    elbowLBend: 1.5,
    bodyBow: 0.2,
    bodyLift: 0.03 + 0.015 * wave(p, 2),
    bodyLean: 0.07 * sway,
    bodyYaw: 0.12 * sway,
    headPitch: -0.3,
    headRoll: 0.06 * sway,
  });
}

/** Drumming: forearms beating down in turn in front of the body, head nodding to the beat. */
function drummer(p: number): RobotPose {
  const beat = wave(p, 2);
  return pose({
    armLForward: 0.55 + 0.14 * beat,
    armRForward: 0.55 - 0.14 * beat,
    armLRaise: 0.22,
    armRRaise: 0.22,
    elbowLBend: 1.35 + 0.55 * beat,
    elbowRBend: 1.35 - 0.55 * beat,
    headPitch: 0.1 * Math.abs(beat),
    headYaw: 0.08 * wave(p),
    bodyLift: 0.006 * Math.abs(beat),
    bodyBow: 0.05,
  });
}

// --- quick-draw duel ------------------------------------------------------------------------

/** Gunslinger stance: slight crouch, chin down, hands hovering beside the hips, fingers itching. */
const READY = pose({
  armLRaise: 0.48,
  armRRaise: 0.48,
  armLForward: -0.08,
  armRForward: -0.08,
  elbowLBend: 0.6,
  elbowRBend: 0.6,
  bodyBow: 0.08,
  bodyLift: -0.012,
  headPitch: 0.12,
});

function duelReady(p: number): RobotPose {
  const twitch = 0.04 * wave(p, 3);
  return {
    ...READY,
    elbowLBend: READY.elbowLBend + twitch,
    elbowRBend: READY.elbowRBend - twitch,
    bodyLean: 0.012 * wave(p),
  };
}

/** The draw: the right arm whips up to point straight ahead, kicks back once, then lowers. */
const DRAW_AIM = pose({
  armRForward: HALF_PI,
  elbowRBend: 0.08,
  armLRaise: 0.4,
  elbowLBend: 0.5,
  bodyBow: 0.05,
  bodyYaw: 0.18,
  headPitch: 0.06,
});
const DRAW_RECOIL = pose({
  ...DRAW_AIM,
  armRForward: HALF_PI + 0.3,
  elbowRBend: 0.35,
  bodyBow: -0.04,
});
const DRAW_KEYS: readonly Keyframe[] = [
  [0, REST],
  [0.1, DRAW_AIM],
  [0.16, DRAW_RECOIL],
  [0.28, DRAW_AIM],
  [0.72, DRAW_AIM],
  [1, REST],
];

/** Hit: thrown back with the arms flung out, a hand to the chest, staggering, slumping, recovery. */
const HIT_KEYS: readonly Keyframe[] = [
  [0, REST],
  [
    0.09,
    pose({
      bodyBow: -0.24,
      headPitch: -0.4,
      armLRaise: 1.3,
      armRRaise: 1.3,
      armLForward: 0.3,
      armRForward: 0.3,
      bodyLift: 0.01,
    }),
  ],
  [
    0.3,
    pose({
      bodyBow: -0.1,
      bodyLean: 0.12,
      headPitch: -0.15,
      headRoll: 0.2,
      armRForward: 1.0,
      armRRaise: -0.35,
      elbowRBend: 2.0,
      armLRaise: 0.7,
    }),
  ],
  [
    0.45,
    pose({
      bodyLean: -0.12,
      bodyBow: 0.08,
      headRoll: -0.2,
      armRForward: 1.0,
      armRRaise: -0.35,
      elbowRBend: 2.0,
      armLRaise: 0.4,
    }),
  ],
  [
    0.62,
    pose({
      bodyBow: 0.34,
      bodyLift: -0.02,
      headPitch: 0.6,
      armLForward: 0.35,
      armRForward: 0.35,
    }),
  ],
  [
    0.84,
    pose({
      bodyBow: 0.34,
      bodyLift: -0.02,
      headPitch: 0.6,
      armLForward: 0.35,
      armRForward: 0.35,
    }),
  ],
  [1, REST],
];

/** Win: fist to the shoulder, then two big pumps straight up with a little hop each. */
function duelWin(p: number): RobotPose {
  const h = hold(p, 0.14);
  const up = smoothstep(0.5 + 0.5 * wave(p, 2, -HALF_PI) * 1.4); // 0 = fist low, 1 = fist high
  return pose({
    armRForward: (1.3 + 1.45 * up) * h,
    elbowRBend: (2.2 - 2.0 * up) * h,
    armLRaise: 0.35 * h,
    elbowLBend: 1.2 * h,
    bodyLift: 0.045 * bump(p * 2) * up + 0.045 * bump(p * 2 - 1) * up,
    headPitch: -0.18 * h,
    bodyBow: -0.04 * h,
  });
}

export const ACT_MOTION_NAMES = [
  'act_bird',
  'act_boxer',
  'act_swimmer',
  'act_dancer',
  'act_robot',
  'act_sleeping',
  'act_superhero',
  'act_drummer',
] as const;

export const GAME_MOTIONS: Readonly<Record<string, ProceduralMotion>> = {
  act_bird: { durationS: 1.5, loop: true, sample: bird },
  act_boxer: { durationS: 1.5, loop: true, sample: boxer },
  act_swimmer: { durationS: 2.2, loop: true, sample: swimmer },
  act_dancer: { durationS: 3.2, loop: true, sample: dancer },
  act_robot: { durationS: 3.2, loop: true, sample: robotDance },
  act_sleeping: { durationS: 3.6, loop: true, sample: sleeping },
  act_superhero: { durationS: 2.6, loop: true, sample: superhero },
  act_drummer: { durationS: 1.0, loop: true, sample: drummer },
  duel_ready: { durationS: 2.4, loop: true, sample: duelReady },
  duel_draw: {
    durationS: 1.5,
    loop: false,
    attackS: 0.05,
    sample: (p) => throughKeys(p, DRAW_KEYS),
  },
  duel_hit: { durationS: 3.0, loop: false, attackS: 0.05, sample: (p) => throughKeys(p, HIT_KEYS) },
  duel_win: { durationS: 2.2, loop: false, sample: duelWin },
};
