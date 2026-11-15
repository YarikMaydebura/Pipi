// Moves the whole pet drawing inside its window with CSS transforms (Web Animations API, so it
// stays on the compositor): the leap out of the window toward the robot side, and the leap
// back in. With reduced motion it is a short fade instead.
import type { RobotSide } from '@pipi/shared';

export interface StageMotion {
  /** Leap out of the window toward `side`; ends invisible. */
  leave(side: RobotSide, durationMs: number): Promise<void>;
  /** Put Pipi just outside the window on `side` (before the window is shown). */
  placeOutside(side: RobotSide): void;
  /** Leap from outside (see placeOutside) to the resting place. */
  enter(side: RobotSide, durationMs: number): Promise<void>;
  fade(visible: boolean, durationMs: number): Promise<void>;
  /** Back to the resting place, visible, no animation running. */
  reset(): void;
}

const dir = (side: RobotSide): number => (side === 'right' ? 1 : -1);

/** Keyframes of the leap out (pure, unit-tested). Translations are % of the pet's own size. */
export function leaveKeyframes(side: RobotSide): Keyframe[] {
  const d = dir(side);
  return [
    { transform: 'translate(0%, 0%) rotate(0deg)', opacity: 1 },
    { transform: `translate(${d * 30}%, -24%) rotate(${d * 10}deg)`, opacity: 1, offset: 0.4 },
    { transform: `translate(${d * 105}%, 4%) rotate(${d * 26}deg)`, opacity: 1, offset: 0.85 },
    { transform: `translate(${d * 125}%, 14%) rotate(${d * 32}deg)`, opacity: 0 },
  ];
}

/** Keyframes of the leap in: from above the robot-side edge, an arc down to the resting place. */
export function enterKeyframes(side: RobotSide): Keyframe[] {
  const d = dir(side);
  return [
    { transform: `translate(${d * 120}%, -30%) rotate(${-d * 24}deg)`, opacity: 0 },
    { transform: `translate(${d * 95}%, -34%) rotate(${-d * 18}deg)`, opacity: 1, offset: 0.12 },
    { transform: `translate(${d * 35}%, -26%) rotate(${-d * 8}deg)`, opacity: 1, offset: 0.55 },
    { transform: 'translate(0%, 0%) rotate(0deg)', opacity: 1 },
  ];
}

export function createStageMotion(element: HTMLElement, reducedMotion: () => boolean): StageMotion {
  let running: Animation[] = [];

  const play = async (keyframes: Keyframe[], durationMs: number, easing: string) => {
    const animation = element.animate(keyframes, {
      duration: durationMs,
      easing,
      fill: 'forwards',
    });
    running = [...running, animation];
    try {
      await animation.finished;
    } catch {
      // cancelled by reset(): fine
    }
  };

  const fade = (visible: boolean, durationMs: number): Promise<void> =>
    play([{ opacity: visible ? 0 : 1 }, { opacity: visible ? 1 : 0 }], durationMs, 'ease-out');

  const clear = (): void => {
    for (const animation of running) animation.cancel();
    running = [];
    element.style.removeProperty('transform');
    element.style.removeProperty('opacity');
  };

  return {
    leave(side, durationMs) {
      if (reducedMotion()) return fade(false, Math.min(durationMs, 300));
      return play(leaveKeyframes(side), durationMs, 'cubic-bezier(0.3, 0.1, 0.7, 1)');
    },
    placeOutside(side) {
      clear();
      const first = enterKeyframes(side)[0];
      element.style.transform = reducedMotion() ? 'none' : String(first?.transform ?? 'none');
      element.style.opacity = '0';
    },
    async enter(side, durationMs) {
      const keyframes = reducedMotion() ? [{ opacity: 0 }, { opacity: 1 }] : enterKeyframes(side);
      await play(keyframes, reducedMotion() ? 300 : durationMs, 'cubic-bezier(0.2, 0.6, 0.35, 1)');
      clear();
    },
    fade,
    reset: clear,
  };
}
