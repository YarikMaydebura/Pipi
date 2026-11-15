// Automatic blinking: a random pause of 3–6 s, then a quick close-open (sometimes twice).
// Pure and time-driven (pass `now` in seconds), so it is easy to test.

export const BLINK_MIN_GAP_S = 3;
export const BLINK_MAX_GAP_S = 6;
export const BLINK_DURATION_S = 0.16;
const DOUBLE_BLINK_CHANCE = 0.2;
const DOUBLE_BLINK_GAP_S = 0.22;

export type RandomSource = () => number; // returns [0, 1), like Math.random

export class BlinkScheduler {
  private nextAt: number;
  private blinkStart = Number.NEGATIVE_INFINITY;

  constructor(
    now: number,
    private readonly random: RandomSource = Math.random,
  ) {
    this.nextAt = now + this.gap();
  }

  /** Start a blink right now (e.g. for the `blink` eye state). */
  trigger(now: number): void {
    this.blinkStart = now;
    this.nextAt = now + this.gap();
  }

  /** How closed the eyes are at `now`: 0 open .. 1 closed. Call once per frame. */
  update(now: number): number {
    if (now >= this.nextAt) {
      this.blinkStart = now;
      const isDouble = this.random() < DOUBLE_BLINK_CHANCE;
      this.nextAt = isDouble ? now + DOUBLE_BLINK_GAP_S : now + this.gap();
    }
    return blinkAmount(now - this.blinkStart);
  }

  private gap(): number {
    return BLINK_MIN_GAP_S + this.random() * (BLINK_MAX_GAP_S - BLINK_MIN_GAP_S);
  }
}

/** Shape of one blink over time since it started: fast close, slightly slower open. */
export function blinkAmount(elapsed: number): number {
  if (elapsed < 0 || elapsed > BLINK_DURATION_S) return 0;
  const closeTime = BLINK_DURATION_S * 0.4;
  return elapsed < closeTime
    ? elapsed / closeTime
    : 1 - (elapsed - closeTime) / (BLINK_DURATION_S - closeTime);
}
