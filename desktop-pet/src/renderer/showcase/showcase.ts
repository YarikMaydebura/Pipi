// Showcase mode: plays the playlist over and over on the real pet (no brain). One step at a
// time; a step that fails is skipped, because the show must go on during a presentation.
import type { EyeState } from '@pipi/shared';
import { SHOWCASE_STEPS, type ShowcaseStep } from './playlist';

/** The few things the showcase does with Pipi (showcaseActor.ts implements it on the pet). */
export interface ShowcaseActor {
  setEyes(state: EyeState): void;
  playMotion(name: string): void;
  /** Heart eyes, big smile and bright cheeks for `durationMs`. */
  loveFace(durationMs: number): void;
  /** Caption bubble + talking animation, no sound. */
  say(text: string): void;
  /** Resolves when Pipi is back on the screen. */
  jumpOutAndBack(): Promise<void>;
}

export interface ShowcaseOptions {
  readonly actor: ShowcaseActor;
  readonly steps?: readonly ShowcaseStep[];
  /** Called when a step starts (the title label). */
  readonly onStep?: (step: ShowcaseStep, index: number, total: number) => void;
  readonly onError?: (step: ShowcaseStep, error: unknown) => void;
  readonly wait?: (ms: number) => Promise<void>;
}

const IDLE_CLIP = 'idle';

const realWait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

/** `?showcase=1` in the page URL (main adds it for `npm run showcase`). */
export function showcaseRequested(search: string): boolean {
  return new URLSearchParams(search).get('showcase') === '1';
}

export class Showcase {
  private readonly steps: readonly ShowcaseStep[];
  private readonly wait: (ms: number) => Promise<void>;
  private running = false;
  private loop: Promise<void> = Promise.resolve();

  constructor(private readonly options: ShowcaseOptions) {
    this.steps = options.steps ?? SHOWCASE_STEPS;
    this.wait = options.wait ?? realWait;
  }

  /** Play the playlist again and again until stop(). */
  start(): void {
    if (this.running || this.steps.length === 0) return;
    this.running = true;
    this.loop = this.repeat();
  }

  /** Ends the show after the step that is playing now. */
  stop(): void {
    this.running = false;
  }

  /** Resolves when a started show has ended (after stop()). */
  get finished(): Promise<void> {
    return this.loop;
  }

  /** One pass through the playlist. */
  async playOnce(): Promise<void> {
    this.running = true;
    await this.pass();
  }

  private async repeat(): Promise<void> {
    while (this.running) await this.pass();
  }

  private async pass(): Promise<void> {
    for (const [index, step] of this.steps.entries()) {
      if (!this.running) return;
      this.options.onStep?.(step, index, this.steps.length);
      try {
        await this.play(step);
      } catch (error: unknown) {
        this.options.onError?.(step, error);
      }
    }
  }

  private async play(step: ShowcaseStep): Promise<void> {
    const { actor } = this.options;
    switch (step.kind) {
      case 'clip':
        actor.setEyes(step.eyes);
        if (step.love) actor.loveFace(step.holdMs);
        actor.playMotion(step.clip);
        return this.wait(step.holdMs);
      case 'eyes':
        actor.playMotion(IDLE_CLIP); // leave a loop that may still be running
        actor.setEyes(step.eyes);
        return this.wait(step.holdMs);
      case 'speak':
        actor.playMotion(IDLE_CLIP);
        actor.say(step.text);
        return this.wait(step.holdMs);
      case 'jump':
        actor.setEyes('happy');
        return actor.jumpOutAndBack();
    }
  }
}
