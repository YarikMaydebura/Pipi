// What any on-screen Pipi (3D or the 2D fallback) can do. PetController talks only to this.
import type { EyeState } from '@pipi/shared';
import type { EyeLook } from '../eyes/eyeFrame';
import type { ScreenPoint } from '../motion/idle';
import type { MouthShape } from '../mouth/mouthShapes';

/**
 * A short-lived face for a reaction (poke, shy, love, …). It overrides the eyes / mouth /
 * cheeks for `durationMs`, then the face follows the brain's eye state again. Fields that are
 * left out are not touched (eyes) or follow the eyes (mouth, cheeks).
 */
export interface FaceFlash {
  readonly eyes?: EyeLook;
  readonly mouth?: MouthShape;
  readonly cheeks?: boolean;
  readonly durationMs: number;
}

export type PetViewKind = '3d' | 'fallback';

export interface PetView {
  readonly kind: PetViewKind;
  setEyeState(state: EyeState): void;
  /** Play a named motion (docs/GAMES.md §2). Returns false if this view does not know it. */
  playMotion(name: string): boolean;
  /**
   * The loop Pipi rests in and returns to after one-shots (idle, talk, listen, think, sleep,
   * dangle, …). `interrupt` cuts a running one-shot; otherwise it finishes first.
   * Returns false if the name is not a loop this view knows.
   */
  setBaseMotion(name: string, interrupt: boolean): boolean;
  /** Show a reaction face for a moment; null ends the current one at once. */
  flashFace(face: FaceFlash | null): void;
  /** Cursor position in window coordinates (CSS px), or null when unknown. */
  setCursor(point: ScreenPoint | null): void;
  /** True when the window point is on Pipi (used for click-through). */
  hitTest(point: ScreenPoint): boolean;
  /** Debug: force a mouth shape; null = the mouth follows the eye state (the default). */
  setMouthOverride(shape: MouthShape | null): void;
  /** Coral cheeks glow bright (they glow softly by default and brightly when happy). */
  setCheeks(on: boolean): void;
  /** Chest light pulses, e.g. while Pipi is speaking. */
  setChestPulse(on: boolean): void;
  /** Loudness of Pipi's voice right now, 0..1 (0 = silent): drives the talking animation. */
  setSpeechLevel(level: number): void;
  setReducedMotion(reduced: boolean): void;
  dispose(): void;
}
