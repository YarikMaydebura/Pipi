// Reconnect delays: 0.5 s, 1 s, 2 s, 4 s, then every 5 s, each with ±20 % jitter so a restarted
// brain is not hit by every body at the same instant.

export interface BackoffOptions {
  readonly baseMs: number;
  readonly maxMs: number;
  readonly jitter: number; // 0.2 = ±20 %
}

export const DEFAULT_BACKOFF: BackoffOptions = { baseMs: 500, maxMs: 5000, jitter: 0.2 };

/** Delay before reconnect attempt number `attempt` (0 = first retry). */
export function backoffDelay(
  attempt: number,
  options: BackoffOptions = DEFAULT_BACKOFF,
  random: () => number = Math.random,
): number {
  const raw = Math.min(options.maxMs, options.baseMs * 2 ** Math.max(0, attempt));
  const spread = 1 + options.jitter * (random() * 2 - 1);
  return Math.round(raw * spread);
}
