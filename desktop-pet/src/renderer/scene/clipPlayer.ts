// Plays the named animation clips of pipi.glb with crossfades. Looping clips (idle, talk,
// think, sleep, listen, dance, look_around, dangle) repeat; the others play once, hold their
// last frame, and (except jump_out) fade back to the BASE loop — idle by default, or whatever
// setBase chose (talk while speaking, dangle while dragged, sleep, …).
import {
  AnimationMixer,
  LoopOnce,
  LoopRepeat,
  type AnimationAction,
  type AnimationClip,
  type Object3D,
} from 'three';
import { HOLD_CLIPS, LOOPING_CLIPS, namesMatch } from './partNames';

const CROSSFADE_S = 0.25;

export class ClipPlayer {
  private readonly mixer: AnimationMixer;
  private readonly actions = new Map<string, AnimationAction>();
  private current: AnimationAction | null = null;
  private base = 'idle';

  constructor(root: Object3D, clips: readonly AnimationClip[]) {
    this.mixer = new AnimationMixer(root);
    for (const clip of clips) {
      const action = this.mixer.clipAction(clip);
      const looping = LOOPING_CLIPS.some((name) => namesMatch(clip.name, name));
      action.setLoop(looping ? LoopRepeat : LoopOnce, Infinity);
      action.clampWhenFinished = !looping;
      this.actions.set(clip.name, action);
    }
    this.mixer.addEventListener('finished', (event) => {
      const clipName = event.action.getClip().name;
      const holds = HOLD_CLIPS.some((name) => namesMatch(clipName, name));
      if (event.action === this.current && !holds) this.play(this.base);
    });
    this.play('idle');
  }

  get hasClips(): boolean {
    return this.actions.size > 0;
  }

  private find(name: string): AnimationAction | undefined {
    for (const [clipName, action] of this.actions) {
      if (namesMatch(clipName, name)) return action;
    }
    return undefined;
  }

  has(name: string): boolean {
    return this.find(name) !== undefined;
  }

  /** Crossfade to the clip called `name`. Returns false if the model has no such clip. */
  play(name: string): boolean {
    const next = this.find(name);
    if (!next) return false;
    if (next === this.current && next.isRunning()) return true;
    next.reset().setEffectiveWeight(1).play();
    if (this.current && this.current !== next) this.current.crossFadeTo(next, CROSSFADE_S, false);
    this.current = next;
    return true;
  }

  /**
   * The loop to return to after one-shots. It shows right away with `interrupt`, or when no
   * one-shot is running; otherwise the one-shot finishes first. False if there is no such clip.
   */
  setBase(name: string, interrupt: boolean): boolean {
    if (!this.has(name)) return false;
    this.base = name;
    const oneShotRunning =
      this.current !== null && this.current.loop === LoopOnce && this.current.isRunning();
    if (interrupt || !oneShotRunning) this.play(name);
    return true;
  }

  update(dt: number): void {
    this.mixer.update(dt);
  }

  dispose(): void {
    this.mixer.stopAllAction();
  }
}
