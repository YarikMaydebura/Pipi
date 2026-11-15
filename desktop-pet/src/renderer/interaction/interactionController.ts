// Runs the reaction policy: forwards pointer events, brain activity and a regular tick to
// ReactionPolicy, and plays the returned steps on the pet (with setTimeout for later steps).
// A new reaction cancels the steps still pending from the previous one.
import type { FaceFlash } from '../pet/PetView';
import {
  ReactionPolicy,
  type BrainActivity,
  type PolicyOptions,
  type Reaction,
  type ReactionStep,
} from './reactionPolicy';

/** What reactions act on (PetController implements it). */
export interface ReactionTarget {
  playMotion(name: string): void;
  setBaseMotion(name: string, interrupt: boolean): void;
  flashFace(face: FaceFlash | null): void;
  /** Sleepy face on (idle sleep) or off (back to the brain's eye state). */
  setDozing(on: boolean): void;
}

export interface InteractionOptions extends PolicyOptions {
  readonly target: ReactionTarget;
  /** Clock in ms (Date.now by default; vitest's fake timers control it). */
  readonly now?: () => number;
  readonly tickMs?: number;
  /** Called with every reaction that starts (debug label). */
  readonly onReaction?: (reaction: Reaction) => void;
}

export const TICK_MS = 250;

export class InteractionController {
  private readonly policy: ReactionPolicy;
  private readonly now: () => number;
  private pending: ReturnType<typeof setTimeout>[] = [];
  private ticker: ReturnType<typeof setInterval> | undefined;

  constructor(private readonly options: InteractionOptions) {
    this.now = options.now ?? Date.now;
    this.policy = new ReactionPolicy(this.now(), options);
  }

  /** Start the idle timeline (hover timing, fidgets, sleep). */
  start(): void {
    if (this.ticker !== undefined) return;
    this.ticker = setInterval(
      () => this.run(this.policy.tick(this.now())),
      this.options.tickMs ?? TICK_MS,
    );
  }

  dispose(): void {
    clearInterval(this.ticker);
    this.ticker = undefined;
    this.cancelPending();
  }

  get calm(): boolean {
    return this.policy.isCalm;
  }

  click(): void {
    this.run(this.policy.click(this.now()));
  }

  hover(over: boolean): void {
    this.run(this.policy.hover(over, this.now()));
  }

  drag(active: boolean): void {
    this.run(this.policy.drag(active, this.now()));
  }

  setCalm(on: boolean): void {
    this.run(this.policy.setCalm(on, this.now()));
  }

  setReducedMotion(on: boolean): void {
    this.policy.setReducedMotion(on);
  }

  /** Every brain message, with the activity after it (and the motion name, if any). */
  brain(activity: BrainActivity, motion?: string): void {
    this.run(this.policy.brain(activity, this.now(), motion));
  }

  private run(reaction: Reaction | null): void {
    if (!reaction) return;
    this.cancelPending();
    this.options.onReaction?.(reaction);
    for (const step of reaction.steps) {
      if (step.atMs <= 0) {
        this.apply(step);
        continue;
      }
      const timer = setTimeout(() => {
        this.pending = this.pending.filter((t) => t !== timer);
        this.apply(step);
      }, step.atMs);
      this.pending = [...this.pending, timer];
    }
  }

  private cancelPending(): void {
    for (const timer of this.pending) clearTimeout(timer);
    this.pending = [];
  }

  private apply(step: ReactionStep): void {
    const { target } = this.options;
    try {
      if (step.dozing !== undefined) target.setDozing(step.dozing);
      if (step.base) target.setBaseMotion(step.base.name, step.base.interrupt);
      if (step.motion) target.playMotion(step.motion);
      if (step.face) target.flashFace(step.face === 'clear' ? null : step.face);
    } catch (error: unknown) {
      // A failing reaction must never break the pet; it just skips this step.
      console.warn('[pipi] reaction step failed:', error);
    }
  }
}
