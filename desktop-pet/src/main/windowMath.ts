// Pure helpers for moving Pipi's window (no Electron imports, so they are unit-tested).
import type { RobotSideName, WindowCommand } from '../preload/bridge';

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

export const SCREEN_MARGIN = 16;
const MAX_SLIDE_MS = 5000;

/** Bottom corner of the work area on `side` (above the taskbar / dock). */
export function cornerPosition(
  workArea: Rect,
  size: { readonly width: number; readonly height: number },
  side: RobotSideName,
  margin = SCREEN_MARGIN,
): Point {
  const x =
    side === 'left' ? workArea.x + margin : workArea.x + workArea.width - size.width - margin;
  return { x: Math.round(x), y: Math.round(workArea.y + workArea.height - size.height) };
}

/** Smooth start and stop. */
export function easeInOutCubic(t: number): number {
  const c = Math.min(1, Math.max(0, t));
  return c < 0.5 ? 4 * c * c * c : 1 - (-2 * c + 2) ** 3 / 2;
}

export function lerpPoint(from: Point, to: Point, t: number): Point {
  return {
    x: Math.round(from.x + (to.x - from.x) * t),
    y: Math.round(from.y + (to.y - from.y) * t),
  };
}

const isSide = (value: unknown): value is RobotSideName => value === 'left' || value === 'right';

/** Validate a window command coming from the renderer; null for anything unexpected. */
export function parseWindowCommand(value: unknown): WindowCommand | null {
  if (typeof value !== 'object' || value === null) return null;
  const { action, side, durationMs } = value as Record<string, unknown>;
  switch (action) {
    case 'hide':
      return { action };
    case 'place':
    case 'show':
      return isSide(side) ? { action, side } : null;
    case 'slide':
      if (!isSide(side) || typeof durationMs !== 'number' || !Number.isFinite(durationMs)) {
        return null;
      }
      return { action, side, durationMs: Math.min(MAX_SLIDE_MS, Math.max(0, durationMs)) };
    default:
      return null;
  }
}
