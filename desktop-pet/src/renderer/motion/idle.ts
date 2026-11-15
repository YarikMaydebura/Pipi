// Idle life (breathing, a gentle sway) and turning the head toward the cursor.
import { pose, ZERO_POSE, type Pose } from './pose';
import { clamp } from '../eyes/eyeFrame';

const BREATH_PERIOD_S = 3.4;
const SWAY_PERIOD_S = 7.3;
const TAU = Math.PI * 2;

/** Small, slow, always-on body movement. Reduced motion keeps Pipi still. */
export function idlePose(t: number, reducedMotion: boolean): Pose {
  if (reducedMotion) return ZERO_POSE;
  const breath = Math.sin((t / BREATH_PERIOD_S) * TAU);
  const sway = Math.sin((t / SWAY_PERIOD_S) * TAU);
  return pose({
    bodyLift: 0.008 * (breath + 1),
    squash: -0.006 * breath,
    headRoll: 0.025 * sway,
    armLRaise: 0.03 * (breath + 1),
    armRRaise: 0.03 * (breath + 1),
    antennaRoll: 0.05 * Math.sin(t * 1.7),
  });
}

export interface ScreenPoint {
  readonly x: number;
  readonly y: number;
}

export interface LookTarget {
  readonly yaw: number;
  readonly pitch: number;
  /** Eye gaze in -1..1 on each axis (eyes move further than the head). */
  readonly gazeX: number;
  readonly gazeY: number;
}

export const NO_LOOK: LookTarget = { yaw: 0, pitch: 0, gazeX: 0, gazeY: 0 };

const MAX_YAW = 0.55;
const MAX_PITCH = 0.3;
/** Imagined distance (CSS px) between Pipi and the cursor plane; larger = calmer turning. */
const VIEW_DISTANCE_PX = 650;
const GAZE_RANGE_PX = 380;

/** Where the head and eyes should point so Pipi looks at `cursor` (window coordinates). */
export function lookAt(cursor: ScreenPoint | null, head: ScreenPoint): LookTarget {
  if (!cursor) return NO_LOOK;
  const dx = cursor.x - head.x;
  const dy = cursor.y - head.y;
  return {
    yaw: clamp(Math.atan2(dx, VIEW_DISTANCE_PX), -MAX_YAW, MAX_YAW),
    pitch: clamp(Math.atan2(dy, VIEW_DISTANCE_PX), -MAX_PITCH, MAX_PITCH),
    gazeX: clamp(dx / GAZE_RANGE_PX, -1, 1),
    gazeY: clamp(dy / GAZE_RANGE_PX, -1, 1),
  };
}
