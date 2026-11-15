// Pure formatting helpers for the WoZ panel (unit-tested in format.test.ts).

/** Latency budget from docs/SYSTEM_DESIGN.md §8: user stops talking -> Pipi speaks. */
export const SLOW_TURN_MS = 2500;

/** Reconnect backoff: 0.5 s, 1 s, 2 s, 4 s, 8 s, then every 10 s. */
export const RECONNECT_BASE_MS = 500;
export const RECONNECT_MAX_MS = 10_000;

/** Seconds as a clock: 245 -> "4:05", 3725 -> "1:02:05". Negative / NaN -> "0:00". */
export function formatClock(seconds: number): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.ceil(seconds)) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}

export interface TimerLike {
  remaining_s: number;
  total_s: number;
}

/**
 * Remaining seconds now, counted down locally since the last state_update arrived.
 * A paused session keeps the value from the brain.
 */
export function remainingSeconds(
  timer: TimerLike,
  receivedAtMs: number,
  nowMs: number,
  paused: boolean,
): number {
  if (paused) return timer.remaining_s;
  const elapsed = Math.max(0, (nowMs - receivedAtMs) / 1000);
  return Math.max(0, timer.remaining_s - elapsed);
}

/** Fraction of the timer that is used up (0..1), for the progress bar. */
export function timerProgress(remaining: number, total: number): number {
  if (!(total > 0)) return 0;
  return Math.min(1, Math.max(0, 1 - remaining / total));
}

/** 850 -> "850 ms", 1234 -> "1.2 s", missing -> "–". */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '–';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function isSlowTurn(totalMs: number | null | undefined): boolean {
  return typeof totalMs === 'number' && totalMs > SLOW_TURN_MS;
}

/** Epoch ms -> local "HH:MM:SS" (matches the brain's log timestamps by eye). */
export function formatTimeOfDay(epochMs: number): string {
  const date = new Date(epochMs);
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
}

export function reconnectDelayMs(attempt: number): number {
  const exponent = Math.max(0, Math.min(attempt, 10));
  return Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** exponent);
}

/** "desktop_pet" -> "Desktop pet", "GAME_CROCODILE" -> "Game crocodile". */
export function humanize(identifier: string): string {
  const words = identifier.replace(/_/g, ' ').toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
