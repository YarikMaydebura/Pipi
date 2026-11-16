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
import { motionSeconds, planMotion, type BaseLoop } from '../motionPlan';
import { PROCEDURAL_MOTIONS } from '../proceduralMotions';
import type { MotionHandle, RobotView } from '../robotController';

const EYE_SIZE = 256;
const seconds = (): number => performance.now() / 1000;

/** The motion being "played" (the 2D face only times it, so acks keep their rhythm). */
interface TimedMotion {
  readonly name: string;
  readonly finished: Promise<void>;
  readonly resolve: () => void;
  timer: ReturnType<typeof setTimeout> | undefined;
}

export class FlatRobotView implements RobotView {
  private readonly eyes = new EyeController(seconds());
  private readonly contexts: CanvasRenderingContext2D[];
  private speechLevel = 0;
  private frameHandle = 0;
  private motion: TimedMotion | null = null;

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

  setBase(loop: BaseLoop, interrupt: boolean): void {
    this.root.dataset['base'] = loop;
    if (interrupt) this.endMotion();
  }

  perform(name: string): MotionHandle | null {
    const plan = planMotion(name, () => false);
    if (plan.kind !== 'procedural') return null;
    const def = PROCEDURAL_MOTIONS[plan.name];
    const lastsS =
      plan.mode === 'once' ? (def?.durationS ?? 1) : motionSeconds(plan.name, plan.mode);
    let motion = this.motion;
    if (!motion || motion.name !== plan.name || plan.mode !== 'held') {
      this.endMotion();
      let resolve = (): void => undefined;
      const finished = new Promise<void>((done) => {
        resolve = done;
      });
      motion = { name: plan.name, finished, resolve, timer: undefined };
      this.motion = motion;
      this.root.dataset['motion'] = plan.name;
    }
    // A held motion that is re-sent keeps going: only its end moves.
    const running = motion;
    clearTimeout(running.timer);
    running.timer = setTimeout(() => {
      if (this.motion === running) this.endMotion();
    }, lastsS * 1000);
    return { finished: running.finished };
  }

  dispose(): void {
    window.cancelAnimationFrame(this.frameHandle);
    this.endMotion();
  }

  private endMotion(): void {
    const motion = this.motion;
    if (!motion) return;
    this.motion = null;
    clearTimeout(motion.timer);
    delete this.root.dataset['motion'];
    motion.resolve();
  }

  private readonly onFrame = (): void => {
    const frame = applySpeechLevel(this.eyes.frame(seconds(), { x: 0, y: 0 }), this.speechLevel);
    const [left, right] = this.contexts;
    if (left) drawEye(left, frame, EYE_SIZE);
    if (right) drawEye(right, mirrorForRightEye(frame), EYE_SIZE);
    this.frameHandle = window.requestAnimationFrame(this.onFrame);
  };
}
