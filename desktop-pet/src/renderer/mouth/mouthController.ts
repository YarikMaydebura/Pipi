// Decides which mouth is visible: a debug override (key `o`) wins, then a reaction's mouth
// flash (e.g. small_o when poked), then a short big smile after a happy motion (celebrate, …),
// otherwise the mouth that goes with the eye state.
import type { EyeLook, MouthShape } from '@pipi/shared/look';
import { computeMouthFrame, mouthForState, type MouthFrame } from '@pipi/shared/look';

/** Motions that make Pipi grin while they play. */
export const GRIN_MOTIONS: readonly string[] = [
  'celebrate',
  'happy',
  'excited',
  'signature_wave',
  'giggle',
  'dance',
  'love',
];
export const GRIN_S = 1.6;

export class MouthController {
  private override: MouthShape | null = null;
  private grinUntil = Number.NEGATIVE_INFINITY;
  private flashShape: MouthShape | null = null;
  private flashUntil = Number.NEGATIVE_INFINITY;

  /** Force a mouth shape (debug); null = follow the eye state again. */
  setOverride(shape: MouthShape | null): void {
    this.override = shape;
  }

  /** Show `shape` until `until` (seconds); null clears a running flash. */
  flash(shape: MouthShape | null, until: number): void {
    this.flashShape = shape;
    this.flashUntil = shape ? until : Number.NEGATIVE_INFINITY;
  }

  /** Call when a motion starts; happy motions show a big smile for a moment. */
  onMotion(name: string, now: number): void {
    if (GRIN_MOTIONS.includes(name)) this.grinUntil = now + GRIN_S;
  }

  frame(state: EyeLook, speechLevel: number, now: number): MouthFrame {
    if (this.override) return computeMouthFrame(this.override, speechLevel);
    const base = mouthForState(state);
    if (this.flashShape && base !== 'off' && now < this.flashUntil) {
      return computeMouthFrame(this.flashShape, speechLevel);
    }
    const grin = base !== 'off' && now < this.grinUntil;
    return computeMouthFrame(grin ? 'big_smile' : base, speechLevel);
  }
}
