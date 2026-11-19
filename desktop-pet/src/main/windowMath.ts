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

export interface Size {
  readonly width: number;
  readonly height: number;
}

export const SCREEN_MARGIN = 16;
const MAX_SLIDE_MS = 5000;
/** Showcase mode: Pipi is at most this many times its normal size. */
export const SHOWCASE_MAX_SCALE = 2;

/** Bottom corner of the work area on `side` (above the taskbar / dock). */
export function cornerPosition(
  workArea: Rect,
  size: Size,
  side: RobotSideName,
  margin = SCREEN_MARGIN,
): Point {
  const x =
    side === 'left' ? workArea.x + margin : workArea.x + workArea.width - size.width - margin;
  return { x: Math.round(x), y: Math.round(workArea.y + workArea.height - size.height) };
}

/** Top-left corner that puts a window of `size` in the middle of the work area. */
export function centerPosition(workArea: Rect, size: Size): Point {
  return {
    x: Math.round(workArea.x + (workArea.width - size.width) / 2),
    y: Math.round(workArea.y + (workArea.height - size.height) / 2),
  };
}

/**
 * Showcase window: the normal pet scaled up as far as the work area allows (never above
 * SHOWCASE_MAX_SCALE, never below its normal size), same shape, in the middle of the screen.
 */
export function showcaseBounds(workArea: Rect, base: Size, margin = SCREEN_MARGIN): Rect {
  const fit = Math.min(
    (workArea.width - 2 * margin) / base.width,
    (workArea.height - 2 * margin) / base.height,
  );
  const scale = Math.max(1, Math.min(SHOWCASE_MAX_SCALE, fit));
  const size = { width: Math.round(base.width * scale), height: Math.round(base.height * scale) };
  return { ...centerPosition(workArea, size), ...size };
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
const isDuration = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const clampDuration = (ms: number): number => Math.min(MAX_SLIDE_MS, Math.max(0, ms));

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
      if (!isSide(side) || !isDuration(durationMs)) return null;
      return { action, side, durationMs: clampDuration(durationMs) };
    case 'center':
      return isDuration(durationMs) ? { action, durationMs: clampDuration(durationMs) } : null;
    default:
      return null;
  }
}
