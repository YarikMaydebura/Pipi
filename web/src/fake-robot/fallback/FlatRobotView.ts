// 2D fallback when WebGL / three.js / the model fails: the robot's face as two round eye
// displays with Pipi's eyes (same shared drawer), dimmed while asleep. Motions are timed like
// their procedural versions, so acks keep the same rhythm and the brain cannot tell.
import type { EyeState } from '@pipi/shared';
import {
  applySpeechLevel,
  clamp,
  drawEye,
  EyeController,
  mirrorForRightEye,
} from '@pipi/shared/look';
import { loopGestureSeconds, planMotion, type BaseLoop } from '../motionPlan';
import { PROCEDURAL_MOTIONS } from '../proceduralMotions';
import type { MotionHandle, RobotView } from '../robotController';

const EYE_SIZE = 256;
const seconds = (): number => performance.now() / 1000;

export class FlatRobotView implements RobotView {
  private readonly eyes = new EyeController(seconds());
  private readonly contexts: CanvasRenderingContext2D[];
  private speechLevel = 0;
  private frameHandle = 0;

  constructor(private readonly root: HTMLElement) {
    root.hidden = false;
    this.contexts = [...root.querySelectorAll<HTMLCanvasElement>('canvas')].map((canvas) => {
      canvas.width = EYE_SIZE;
      canvas.height = EYE_SIZE;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('2D canvas is not available');
      return ctx;
    });
    this.frameHandle = window.requestAnimationFrame(this.onFrame);
  }

  setEyes(state: EyeState): void {
    this.eyes.setState(state, seconds());
  }

  setSpeechLevel(level: number): void {
    this.speechLevel = clamp(level, 0, 1);
  }

  setBase(loop: BaseLoop): void {
    this.root.dataset['base'] = loop;
  }

  perform(name: string): MotionHandle | null {
    const plan = planMotion(name, () => false);
    if (plan.kind !== 'procedural') return null;
    const def = PROCEDURAL_MOTIONS[plan.name];
    const durationS = def?.loop ? loopGestureSeconds(plan.name) : (def?.durationS ?? 1);
    this.root.dataset['motion'] = plan.name;
    const finished = new Promise<void>((resolve) =>
      setTimeout(() => {
        if (this.root.dataset['motion'] === plan.name) delete this.root.dataset['motion'];
        resolve();
      }, durationS * 1000),
    );
    return { finished };
  }

  dispose(): void {
    window.cancelAnimationFrame(this.frameHandle);
  }

  private readonly onFrame = (): void => {
    const frame = applySpeechLevel(this.eyes.frame(seconds(), { x: 0, y: 0 }), this.speechLevel);
    const [left, right] = this.contexts;
    if (left) drawEye(left, frame, EYE_SIZE);
    if (right) drawEye(right, mirrorForRightEye(frame), EYE_SIZE);
    this.frameHandle = window.requestAnimationFrame(this.onFrame);
  };
}
