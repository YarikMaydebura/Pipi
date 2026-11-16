// Plays the named clips of alpha_mini.glb with crossfades. The robot always rests in a BASE loop
// (idle, talk, listen, think, sleep); one-shots (nod, signature_wave, wake_up, ...) play once and
// fade back to the base; held motions (act_*, duel_ready) keep going until the next motion, a
// base change with `interrupt` (that is how `stop` ends them) or the safety cap. Every motion
// returns a promise that resolves when it has finished or was replaced, which is how
// activate/deactivate are acked "when the animation has finished".
import {
  AnimationMixer,
  LoopOnce,
  LoopRepeat,
  type AnimationAction,
  type AnimationClip,
  type Object3D,
} from 'three';
import {
  baseFadeSeconds,
  LOOP_CLIPS,
  ONE_SHOT_FADE_S,
  type BaseLoop,
  type MotionMode,
} from '../motionPlan';

interface Running {
  readonly action: AnimationAction;
  readonly mode: MotionMode;
  readonly finished: Promise<void>;
  readonly resolve: () => void;
  timer: ReturnType<typeof setTimeout> | undefined;
}

export interface ClipRequest {
  readonly mode: MotionMode;
  /** `timed` / `held`: return to the base loop after this long (ignored for `once`). */
  readonly seconds: number;
}

const normalise = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[\s._-]/g, '');

export class ClipDirector {
  private readonly mixer: AnimationMixer;
  private readonly actions = new Map<string, AnimationAction>();
  private current: AnimationAction | null = null;
  private base: BaseLoop = 'idle';
  private oneShot: Running | null = null;

  constructor(root: Object3D, clips: readonly AnimationClip[]) {
    this.mixer = new AnimationMixer(root);
    for (const clip of clips) {
      const action = this.mixer.clipAction(clip);
      const loop = LOOP_CLIPS.some((name) => normalise(name) === normalise(clip.name));
      action.setLoop(loop ? LoopRepeat : LoopOnce, Infinity);
      action.clampWhenFinished = !loop;
      this.actions.set(normalise(clip.name), action);
    }
    this.mixer.addEventListener('finished', (event) => {
      // A held motion exported as a non-looping clip stays clamped on its last frame.
      if (this.oneShot?.action === event.action && this.oneShot.mode !== 'held') {
        this.endOneShot(true);
      }
    });
  }

  has(name: string): boolean {
    return this.actions.has(normalise(name));
  }

  get clipCount(): number {
    return this.actions.size;
  }

  private fadeTo(next: AnimationAction, fadeS: number): void {
    if (next === this.current && next.isRunning()) return;
    next.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).play();
    if (this.current && this.current !== next) this.current.crossFadeTo(next, fadeS, false);
    else next.fadeIn(fadeS);
    this.current = next;
  }

  /** Rest in `loop`; shows now if `interrupt` or no one-shot is playing. False if no such clip. */
  setBase(loop: BaseLoop, interrupt: boolean): boolean {
    const action = this.actions.get(normalise(loop));
    if (!action) return false;
    this.base = loop;
    if (this.oneShot && !interrupt) return true; // the one-shot fades into it when done
    this.endOneShot(false);
    this.fadeTo(action, baseFadeSeconds(loop));
    return true;
  }

  /**
   * Play `name`: once, for a few seconds (`timed`), or until replaced (`held`), then return to
   * the base loop. Asking again for the held motion that is already playing keeps it going
   * without a restart. Resolves when it has finished or was replaced; null if the model has no
   * such clip.
   */
  play(name: string, request: ClipRequest): Promise<void> | null {
    const action = this.actions.get(normalise(name));
    if (!action) return null;
    const current = this.oneShot;
    if (
      current &&
      current.action === action &&
      current.mode === 'held' &&
      request.mode === 'held'
    ) {
      this.endAfter(current, request.seconds);
      return current.finished;
    }
    this.endOneShot(false);
    let resolve = (): void => undefined;
    const finished = new Promise<void>((done) => {
      resolve = done;
    });
    const running: Running = { action, mode: request.mode, finished, resolve, timer: undefined };
    this.oneShot = running;
    this.fadeTo(action, ONE_SHOT_FADE_S);
    // `once` ends with the mixer's `finished` event; a looping clip never fires it.
    if (request.mode !== 'once' || action.loop === LoopRepeat) {
      this.endAfter(running, request.seconds);
    }
    return finished;
  }

  /** End the running motion (if any) and fade back to the base loop. */
  endMotion(): void {
    this.endOneShot(true);
  }

  private endAfter(running: Running, seconds: number): void {
    clearTimeout(running.timer);
    running.timer = setTimeout(() => {
      if (this.oneShot === running) this.endOneShot(true);
    }, seconds * 1000);
  }

  private endOneShot(returnToBase: boolean): void {
    const running = this.oneShot;
    if (!running) return;
    this.oneShot = null;
    clearTimeout(running.timer);
    running.resolve();
    if (!returnToBase) return;
    const base = this.actions.get(normalise(this.base));
    if (base) this.fadeTo(base, baseFadeSeconds(this.base));
  }

  update(dt: number): void {
    this.mixer.update(dt);
  }

  dispose(): void {
    this.endOneShot(false);
    this.mixer.stopAllAction();
  }
}
