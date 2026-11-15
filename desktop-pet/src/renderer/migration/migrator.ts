// Pipi's jump off the screen (into the robot) and back. Choreography for `jump_out`:
//   1. hop along the bottom of the screen to the corner on the robot side (main moves the
//      window, Pipi hops), 2. crouch and leap out of the window over the screen edge,
//   3. the window hides.
// `jump_in` is the reverse: the window appears in that corner, Pipi leaps in from the edge,
// lands with a squash and shakes itself. Each call resolves when the animation has finished,
// which is when the pet acks activate/deactivate to the brain.
// The model's `jump_out` / `jump_in` glb clips are used when they exist (PetView.playMotion
// prefers clips), else the procedural motions of the same name.
import type { RobotSide } from '@pipi/shared';
import type { WindowCommand } from '../../preload/bridge';
import type { StageMotion } from './stageMotion';

export interface WindowControl {
  command(command: WindowCommand): Promise<boolean>;
}

/** What the migrator needs from the current PetView. */
export interface MotionTarget {
  playMotion(name: string): boolean;
}

export const MIGRATION_TIMING = {
  slideMs: 900, // hop along the bottom edge to the corner
  hopEveryMs: 450,
  crouchMs: 220, // jump_out motion crouches before the leap
  leaveMs: 700,
  enterMs: 750,
  landingMs: 650, // shake-off after landing (rest of the jump_in motion)
  fadeMs: 400,
} as const;

export interface MigratorDeps {
  readonly window: WindowControl | null; // null: no Electron bridge (plain browser)
  readonly stage: StageMotion;
  readonly view: () => MotionTarget;
  readonly wait?: (ms: number) => Promise<void>;
}

const realWait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

export class Migrator {
  private side: RobotSide = 'right';
  private placed = false;
  private away = false;
  private queue: Promise<unknown> = Promise.resolve();
  private readonly wait: (ms: number) => Promise<void>;

  constructor(private readonly deps: MigratorDeps) {
    this.wait = deps.wait ?? realWait;
  }

  get robotSide(): RobotSide {
    return this.side;
  }

  /** True while Pipi is off the screen (after jump_out / fade_out). */
  get isAway(): boolean {
    return this.away;
  }

  /** From body_config. The first time (or when the side changes) Pipi moves to that corner. */
  setRobotSide(side: RobotSide): Promise<void> {
    return this.serial(async () => {
      const changed = side !== this.side;
      this.side = side;
      if ((changed || !this.placed) && !this.away) {
        await this.window({ action: 'place', side });
      }
      this.placed = true;
    });
  }

  jumpOut(): Promise<void> {
    return this.serial(async () => {
      if (this.away) return;
      const t = MIGRATION_TIMING;
      const hops = this.hopAlong(t.slideMs);
      await Promise.all([
        this.window({ action: 'slide', side: this.side, durationMs: t.slideMs }),
        hops,
      ]);
      this.deps.view().playMotion('jump_out');
      await this.wait(t.crouchMs);
      await this.deps.stage.leave(this.side, t.leaveMs);
      await this.hideWindow();
      this.away = true;
    });
  }

  jumpIn(): Promise<void> {
    return this.serial(async () => {
      const t = MIGRATION_TIMING;
      this.deps.stage.placeOutside(this.side);
      await this.window({ action: 'show', side: this.side });
      this.away = false;
      this.deps.view().playMotion('jump_in');
      await this.deps.stage.enter(this.side, t.enterMs);
      await this.wait(t.landingMs);
    });
  }

  fadeOut(): Promise<void> {
    return this.serial(async () => {
      if (this.away) return;
      await this.deps.stage.fade(false, MIGRATION_TIMING.fadeMs);
      await this.hideWindow();
      this.away = true;
    });
  }

  fadeIn(): Promise<void> {
    return this.serial(async () => {
      this.deps.stage.reset();
      // Start the fade (from transparent) before the window appears, so nothing flashes.
      const fading = this.deps.stage.fade(true, MIGRATION_TIMING.fadeMs);
      await this.window({ action: 'show', side: this.side });
      this.away = false;
      await fading;
      this.deps.stage.reset();
    });
  }

  /** Make sure Pipi is visible (e.g. `activate: wake_up` after being away). */
  appear(): Promise<void> {
    return this.serial(async () => {
      if (!this.away) return;
      this.deps.stage.reset();
      await this.window({ action: 'show', side: this.side });
      this.away = false;
    });
  }

  private async hopAlong(durationMs: number): Promise<void> {
    for (let at = 0; at < durationMs; at += MIGRATION_TIMING.hopEveryMs) {
      this.deps.view().playMotion('hop');
      await this.wait(Math.min(MIGRATION_TIMING.hopEveryMs, durationMs - at));
    }
  }

  private async hideWindow(): Promise<void> {
    if (this.deps.window) {
      await this.window({ action: 'hide' });
      this.deps.stage.reset(); // the hidden window shows Pipi in place next time
    }
    // Without a bridge the stage stays invisible (leave/fade ended at opacity 0).
    this.deps.view().playMotion('idle');
  }

  private async window(command: WindowCommand): Promise<void> {
    if (!this.deps.window) return;
    const ok = await this.deps.window.command(command);
    if (!ok) throw new Error(`window command '${command.action}' was rejected`);
  }

  /** One migration at a time: a second request waits for the first to finish. */
  private serial(task: () => Promise<void>): Promise<void> {
    const next = this.queue.then(task, task);
    this.queue = next.catch(() => undefined);
    return next;
  }
}
