// Plays the named clips of alpha_mini.glb with crossfades. The robot always rests in a BASE loop
// (idle, talk, listen, think, sleep); one-shots (nod, signature_wave, wake_up, ...) play once and
// fade back to the base. Every one-shot returns a promise that resolves when it has finished or
// was replaced, which is how activate/deactivate are acked "when the animation has finished".
import {
  AnimationMixer,
  LoopOnce,
  LoopRepeat,
  type AnimationAction,
  type AnimationClip,
  type Object3D,
} from 'three';
import { baseFadeSeconds, isLoopClip, ONE_SHOT_FADE_S, type BaseLoop } from '../motionPlan';

interface Running {
  readonly action: AnimationAction;
  readonly resolve: () => void;
  timer: ReturnType<typeof setTimeout> | undefined;
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
      const loop = isLoopClip(normalise(clip.name)) || isLoopClip(clip.name);
      action.setLoop(loop ? LoopRepeat : LoopOnce, Infinity);
      action.clampWhenFinished = !loop;
      this.actions.set(normalise(clip.name), action);
    }
    this.mixer.addEventListener('finished', (event) => {
      if (this.oneShot?.action === event.action) this.endOneShot(true);
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
   * Play `name` once (or a loop clip for `loopSeconds`), then return to the base loop.
   * Resolves when it has finished or was replaced; null if the model has no such clip.
   */
  play(name: string, loopSeconds: number): Promise<void> | null {
    const action = this.actions.get(normalise(name));
    if (!action) return null;
    this.endOneShot(false);
    return new Promise<void>((resolve) => {
      const running: Running = { action, resolve, timer: undefined };
      this.oneShot = running;
      this.fadeTo(action, ONE_SHOT_FADE_S);
      if (action.loop === LoopRepeat) {
        running.timer = setTimeout(() => {
          if (this.oneShot === running) this.endOneShot(true);
        }, loopSeconds * 1000);
      }
    });
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
