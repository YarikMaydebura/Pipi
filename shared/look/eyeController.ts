// Decides which eye state is shown right now: the state the brain asked for, an optional
// short-lived override (e.g. happy after a poke), and automatic blinking.
import type { EyeState } from '../protocol';
import { BlinkScheduler, type RandomSource } from './blink';
import { canAutoBlink, computeEyeFrame, type EyeFrame, type EyeLook } from './eyeFrame';

interface Override {
  readonly state: EyeLook;
  readonly until: number;
}

export class EyeController {
  private baseState: EyeState = 'idle';
  private override: Override | null = null;
  private readonly blinks: BlinkScheduler;

  constructor(now: number, random?: RandomSource) {
    this.blinks = new BlinkScheduler(now, random);
  }

  /** `blink` is a one-shot action: it blinks once and keeps the current state. */
  setState(state: EyeState, now: number): void {
    if (state === 'blink') {
      this.blinks.trigger(now);
      return;
    }
    this.baseState = state;
    this.override = null;
  }

  /** Show `state` for `durationS` seconds, then return to the requested state. */
  flash(state: EyeLook, now: number, durationS: number): void {
    this.override = { state, until: now + durationS };
  }

  /** End a flash early (back to the requested state). */
  clearFlash(): void {
    this.override = null;
  }

  /** The state currently visible (ignoring blinks). */
  visibleState(now: number): EyeLook {
    if (this.override && now < this.override.until) return this.override.state;
    return this.baseState;
  }

  /** The state the brain asked for most recently. */
  requestedState(): EyeState {
    return this.baseState;
  }

  frame(now: number, gaze: { x: number; y: number }, autoBlink = true): EyeFrame {
    const state = this.visibleState(now);
    const blinkValue = this.blinks.update(now);
    const blink = autoBlink && canAutoBlink(state) ? blinkValue : 0;
    return computeEyeFrame(state, now, { gaze, blink });
  }
}
