// The controller talks to ONE RobotView; this one forwards to the current real view and lets
// main.ts swap the 3D scene for the 2D fallback mid-session without losing the eye state or the
// resting loop.
import type { EyeState } from '@pipi/shared';
import type { BaseLoop } from './motionPlan';
import type { MotionHandle, RobotView } from './robotController';

export interface DisposableView extends RobotView {
  dispose(): void;
}

export class SwitchableView implements RobotView {
  private eyes: EyeState = 'off';
  private base: BaseLoop = 'sleep';

  constructor(private view: DisposableView) {}

  get current(): DisposableView {
    return this.view;
  }

  replace(next: DisposableView): void {
    this.view.dispose();
    this.view = next;
    next.setEyes(this.eyes);
    next.setBase(this.base, true);
  }

  setEyes(state: EyeState): void {
    if (state !== 'blink') this.eyes = state;
    this.view.setEyes(state);
  }

  setSpeechLevel(level: number): void {
    this.view.setSpeechLevel(level);
  }

  setBase(loop: BaseLoop, interrupt: boolean): void {
    this.base = loop;
    this.view.setBase(loop, interrupt);
  }

  perform(name: string): MotionHandle | null {
    return this.view.perform(name);
  }
}
