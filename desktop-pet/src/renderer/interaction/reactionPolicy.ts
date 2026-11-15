// Decides how Pipi reacts to the user (clicks, hover, drag) and to doing nothing (idle
// fidgets, falling asleep). Pure: no DOM, no timers — every call gets the time `now` (ms) and
// returns a Reaction (a few timed steps) or null. interactionController.ts runs the steps.
//
// Priorities: brain > drag > click reactions > idle fidgets. Never during jump_out / jump_in.
// Calm mode (study FOCUS phase): no fidgets, no sleep, no hover reactions; a click only gets a
// tiny poke. Reduced motion: no spin / dance / celebrate, half as many fidgets.
import type { FaceFlash } from '../pet/PetView';

/** What the brain is making Pipi do right now (PetController derives it from messages). */
export type BrainActivity =
  | 'idle' // nothing: Pipi is free to react on its own
  | 'speaking'
  | 'listening'
  | 'thinking'
  | 'asleep' // deactivate: sleep
  | 'migrating' // jump_out / jump_in / fades in progress: never touch the body
  | 'away'; // off the screen (after jump_out / fade_out)

/** One thing to do, `atMs` after the reaction starts. Applied in field order. */
export interface ReactionStep {
  readonly atMs: number;
  /** Sleepy face on (idle sleep) / off (back to the brain's eye state). */
  readonly dozing?: boolean;
  /** The loop to rest in; `interrupt` cuts a running one-shot. */
  readonly base?: { readonly name: string; readonly interrupt: boolean };
  /** A clip / procedural motion to play now. */
  readonly motion?: string;
  /** A reaction face; 'clear' ends the current one. */
  readonly face?: FaceFlash | 'clear';
}

export interface Reaction {
  /** For the debug label and tests, e.g. "poke:giggle", "double:spin", "fidget:yawn". */
  readonly name: string;
  readonly steps: readonly ReactionStep[];
}

export const REACTION_TIMING = {
  doubleClickMs: 350,
  hoverMs: 1500, // hover this long → shy / love
  hoverFaceMs: 8000, // the shy / love face lasts at most this long
  loveChance: 0.3, // hover → love instead of shy
  burstWindowMs: 3000,
  burstClicks: 4, // this many clicks within the window → celebrate / giggle
  tooManyClicks: 7, // → shake_head ("stop it!")
  danceMs: 3000,
  lookAroundMs: 3000,
  fidgetAfterMs: 20_000, // first fidget after this much quiet
  fidgetMinMs: 15_000,
  fidgetMaxMs: 30_000,
  reducedFidgetFactor: 2, // reduced motion: fidgets twice as rare
  sleepAfterMs: 120_000,
  wakeSurpriseMs: 900,
  brainMotionMs: 2500, // assumed length of a brain `motion` (no fidgets on top of it)
  dragFaceMs: 60_000, // the drag face lasts until release (capped)
} as const;

export type ReactionTiming = { readonly [K in keyof typeof REACTION_TIMING]: number };

/** Approximate one-shot lengths (ms): long enough to block lower-priority reactions. */
const CLIP_MS: Readonly<Record<string, number>> = {
  poke: 700,
  giggle: 1200,
  surprised: 900,
  spin: 1100,
  happy: 1200,
  celebrate: 1600,
  shake_head: 1000,
  land: 600,
  yawn: 2200,
  nod: 900,
};
const clipMs = (name: string): number => CLIP_MS[name] ?? 1000;

/** Who owns the body right now; a reaction may only interrupt equal or lower levels. */
const LEVEL = {
  fidget: 0,
  poke: 1,
  hover: 1,
  land: 1,
  double: 2,
  wake: 2,
  burst: 3,
  stop: 4,
  drag: 5,
  brain: 6,
} as const;
type BusyKind = keyof typeof LEVEL;

interface Busy {
  readonly kind: BusyKind;
  readonly until: number;
}

const POKE_FACES: Readonly<Record<string, FaceFlash>> = {
  poke: { eyes: 'happy', mouth: 'big_smile', cheeks: true, durationMs: 1000 },
  giggle: { eyes: 'happy', mouth: 'big_smile', cheeks: true, durationMs: 1200 },
  surprised: { eyes: 'surprised', mouth: 'small_o', cheeks: true, durationMs: 1000 },
};
const HAPPY_FACE: FaceFlash = { eyes: 'happy', mouth: 'big_smile', cheeks: true, durationMs: 1600 };

export interface PolicyOptions {
  /** 0 ≤ r < 1; inject a fixed sequence in tests. */
  readonly random?: () => number;
  readonly timing?: Partial<ReactionTiming>;
}

export class ReactionPolicy {
  private readonly random: () => number;
  private readonly timing: ReactionTiming;
  private activity: BrainActivity = 'idle';
  private calm = false;
  private reduced = false;
  private dragging = false;
  private dozing = false;
  private hovering: { since: number; reacted: boolean } | null = null;
  private clicks: number[] = [];
  private lastClickAt = Number.NEGATIVE_INFINITY;
  private lastClickWasDouble = false;
  private busy: Busy | null = null;
  private lastInteractionAt: number;
  private nextFidgetAt: number;
  private readonly lastPick = new Map<string, string>();

  constructor(now: number, options: PolicyOptions = {}) {
    this.random = options.random ?? Math.random;
    this.timing = { ...REACTION_TIMING, ...options.timing };
    this.lastInteractionAt = now;
    this.nextFidgetAt = now + this.timing.fidgetAfterMs;
  }

  get isDozing(): boolean {
    return this.dozing;
  }

  get isCalm(): boolean {
    return this.calm;
  }

  get currentActivity(): BrainActivity {
    return this.activity;
  }

  setReducedMotion(on: boolean): void {
    this.reduced = on;
  }

  /** Calm mode on/off. Turning it on wakes a dozing Pipi quietly. */
  setCalm(on: boolean, now: number): Reaction | null {
    this.calm = on;
    this.touch(now);
    if (!on || !this.dozing) return null;
    this.dozing = false;
    return { name: 'calm', steps: [{ atMs: 0, dozing: false, base: this.baseStep(false) }] };
  }

  /**
   * Any message from the brain. `activity` is the state after it; `motion` is set when the
   * brain played a named motion. Brain commands always win over the pet's own reactions.
   */
  brain(activity: BrainActivity, now: number, motion?: string): Reaction | null {
    const changed = activity !== this.activity;
    const wasDozing = this.dozing;
    const ownsBody = this.busy !== null && this.busy.kind !== 'brain' && now < this.busy.until;
    this.activity = activity;
    this.touch(now);
    this.dozing = false;
    if (this.hovering) this.hovering.reacted = true;
    if (motion !== undefined) this.busy = { kind: 'brain', until: now + this.timing.brainMotionMs };
    else if (changed) this.busy = null;

    if (this.isBlocked()) {
      // Never touch the body during a migration; only drop the sleepy face if it was on.
      return wasDozing ? { name: 'brain:away', steps: [{ atMs: 0, dozing: false }] } : null;
    }
    if (changed) {
      return {
        name: `brain:${activity}`,
        steps: [
          {
            atMs: 0,
            ...(wasDozing ? { dozing: false } : {}),
            base: this.baseStep(ownsBody),
            face: 'clear',
          },
        ],
      };
    }
    // A brain motion cancels the pet's pending steps (e.g. "dance → back to idle").
    if (motion !== undefined || wasDozing) {
      const wake: ReactionStep = { atMs: 0, dozing: false, base: this.baseStep(false) };
      return { name: 'brain', steps: wasDozing ? [wake] : [] };
    }
    return null;
  }

  /** A click on Pipi (a press without dragging). */
  click(now: number): Reaction | null {
    this.touch(now);
    this.clicks = [...this.clicks.filter((t) => now - t < this.timing.burstWindowMs), now];
    if (this.hovering) this.hovering = { since: now, reacted: false };
    if (this.isBlocked() || this.dragging) return null;
    if (this.activity !== 'idle') {
      // Brain-driven speech / listening is never interrupted: only the cheeks light up.
      return { name: 'acknowledge', steps: [{ atMs: 0, face: { cheeks: true, durationMs: 600 } }] };
    }
    if (this.dozing) return this.wake(now);
    if (this.calm) {
      return this.react(now, 'poke', 'calm:poke', [
        { atMs: 0, motion: 'poke', face: { eyes: 'happy', durationMs: 700 } },
      ]);
    }
    return this.escalate(now);
  }

  /** The cursor entered (true) or left (false) Pipi. */
  hover(over: boolean, now: number): Reaction | null {
    if (over) {
      this.hovering = { since: now, reacted: false };
      return null;
    }
    this.hovering = null;
    if (this.busy?.kind !== 'hover' || now >= this.busy.until) return null;
    this.busy = null;
    return { name: 'hover:end', steps: [{ atMs: 0, face: 'clear', base: this.baseStep(true) }] };
  }

  /** Dragging started (true) or ended (false). */
  drag(active: boolean, now: number): Reaction | null {
    this.touch(now);
    this.dragging = active;
    this.hovering = null;
    if (this.isBlocked()) return null;
    const wasDozing = this.dozing;
    this.dozing = false;
    if (this.activity !== 'idle') return null; // the brain owns the body
    if (active) {
      this.busy = { kind: 'drag', until: Number.POSITIVE_INFINITY };
      return {
        name: 'drag:dangle',
        steps: [
          {
            atMs: 0,
            ...(wasDozing ? { dozing: false } : {}),
            base: { name: 'dangle', interrupt: true },
            face: { eyes: 'surprised', mouth: 'small_o', durationMs: 600 },
          },
          { atMs: 600, face: { ...HAPPY_FACE, durationMs: this.timing.dragFaceMs } },
        ],
      };
    }
    this.busy = null; // the drag lock ends with the drag
    return this.react(now, 'land', 'drag:land', [
      {
        atMs: 0,
        base: { name: 'idle', interrupt: true },
        motion: 'land',
        face: { eyes: 'happy', mouth: 'big_smile', durationMs: 900 },
      },
    ]);
  }

  /** Call regularly (a few times per second): hover timing, idle fidgets, falling asleep. */
  tick(now: number): Reaction | null {
    if (this.busy && now >= this.busy.until) this.busy = null;
    if (this.isBlocked() || this.activity !== 'idle' || this.dragging || this.dozing) return null;
    if (this.busy) return null;
    const hover = this.hoverReaction(now);
    if (hover || this.calm) return hover;
    if (now - this.lastInteractionAt >= this.timing.sleepAfterMs) return this.fallAsleep(now);
    if (now >= this.nextFidgetAt) return this.fidget(now);
    return null;
  }

  // --- helpers --------------------------------------------------------------------------------

  private isBlocked(): boolean {
    return this.activity === 'migrating' || this.activity === 'away';
  }

  /** The loop that fits the current state. */
  private baseLoop(): string {
    switch (this.activity) {
      case 'speaking':
        return 'talk';
      case 'listening':
        return 'listen';
      case 'thinking':
        return 'think';
      case 'asleep':
        return 'sleep';
      default:
        return this.dragging ? 'dangle' : this.dozing ? 'sleep' : 'idle';
    }
  }

  private baseStep(interrupt: boolean): { name: string; interrupt: boolean } {
    return { name: this.baseLoop(), interrupt };
  }

  private touch(now: number): void {
    this.lastInteractionAt = now;
    this.nextFidgetAt = now + this.timing.fidgetAfterMs * this.fidgetFactor();
  }

  private fidgetFactor(): number {
    return this.reduced ? this.timing.reducedFidgetFactor : 1;
  }

  /** Random choice that never repeats the previous pick of the same group. */
  private pick(group: string, options: readonly string[]): string {
    const last = this.lastPick.get(group);
    const pool = options.length > 1 ? options.filter((o) => o !== last) : options;
    const index = Math.min(pool.length - 1, Math.floor(this.random() * pool.length));
    const choice = pool[index] ?? options[0] ?? 'nod';
    this.lastPick.set(group, choice);
    return choice;
  }

  /** Start a reaction if it may interrupt whatever runs now. */
  private react(
    now: number,
    kind: BusyKind,
    name: string,
    steps: readonly ReactionStep[],
    durationMs = this.lengthOf(steps),
  ): Reaction | null {
    const running = this.busy && now < this.busy.until ? this.busy : null;
    if (running && LEVEL[running.kind] > LEVEL[kind]) return null;
    this.busy = { kind, until: now + durationMs };
    return { name, steps };
  }

  private lengthOf(steps: readonly ReactionStep[]): number {
    return Math.max(0, ...steps.map((s) => s.atMs + (s.motion ? clipMs(s.motion) : 0)));
  }

  private escalate(now: number): Reaction | null {
    const recent = this.clicks.length;
    const isDouble =
      now - this.lastClickAt <= this.timing.doubleClickMs && !this.lastClickWasDouble;
    this.lastClickAt = now;
    this.lastClickWasDouble = false;

    if (recent >= this.timing.tooManyClicks) {
      this.clicks = [];
      return this.react(now, 'stop', 'stop:shake_head', [
        {
          atMs: 0,
          motion: 'shake_head',
          face: { eyes: 'determined', mouth: 'wavy', durationMs: 1400 },
        },
      ]);
    }
    if (recent === this.timing.burstClicks) {
      const motion = this.reduced ? 'giggle' : this.pick('burst', ['celebrate', 'giggle']);
      return this.react(now, 'burst', `burst:${motion}`, [{ atMs: 0, motion, face: HAPPY_FACE }]);
    }
    if (isDouble) {
      this.lastClickWasDouble = true;
      return this.doubleClick(now);
    }
    const motion = this.pick('poke', ['poke', 'giggle', 'surprised']);
    return this.react(now, 'poke', `poke:${motion}`, [
      { atMs: 0, motion, face: POKE_FACES[motion] ?? HAPPY_FACE },
    ]);
  }

  private doubleClick(now: number): Reaction | null {
    if (this.reduced) {
      return this.react(now, 'double', 'double:happy', [
        { atMs: 0, motion: 'happy', face: HAPPY_FACE },
      ]);
    }
    const motion = this.pick('double', ['spin', 'dance']);
    if (motion === 'spin') {
      return this.react(now, 'double', 'double:spin', [
        { atMs: 0, motion: 'spin', face: HAPPY_FACE },
      ]);
    }
    const danceMs = this.timing.danceMs;
    return this.react(
      now,
      'double',
      'double:dance',
      [
        { atMs: 0, motion: 'dance', face: { ...HAPPY_FACE, durationMs: danceMs } },
        { atMs: danceMs, base: { name: 'idle', interrupt: true } },
      ],
      danceMs,
    );
  }

  private wake(now: number): Reaction | null {
    this.dozing = false;
    const surprise = this.timing.wakeSurpriseMs;
    return this.react(
      now,
      'wake',
      'wake',
      [
        {
          atMs: 0,
          dozing: false,
          base: { name: 'idle', interrupt: true },
          motion: 'surprised',
          face: { eyes: 'surprised', mouth: 'small_o', durationMs: surprise },
        },
        { atMs: surprise, motion: 'happy', face: HAPPY_FACE },
      ],
      surprise + clipMs('happy'),
    );
  }

  private hoverReaction(now: number): Reaction | null {
    const hovering = this.hovering;
    if (!hovering || hovering.reacted || now - hovering.since < this.timing.hoverMs) return null;
    hovering.reacted = true;
    if (this.calm) return null; // FOCUS: a resting cursor must not set Pipi off
    const love = this.random() < this.timing.loveChance;
    const durationMs = this.timing.hoverFaceMs;
    const step: ReactionStep = love
      ? {
          atMs: 0,
          motion: 'love',
          face: { eyes: 'love', mouth: 'big_smile', cheeks: true, durationMs },
        }
      : {
          atMs: 0,
          motion: 'shy',
          face: { eyes: 'happy', mouth: 'smile', cheeks: true, durationMs },
        };
    return this.react(now, 'hover', love ? 'hover:love' : 'hover:shy', [step], durationMs);
  }

  private fallAsleep(now: number): Reaction | null {
    this.dozing = true;
    const yawnMs = clipMs('yawn');
    return this.react(
      now,
      'fidget',
      'sleep',
      [
        { atMs: 0, motion: 'yawn', face: { eyes: 'sleepy', mouth: 'small_o', durationMs: yawnMs } },
        { atMs: yawnMs, dozing: true, base: { name: 'sleep', interrupt: false } },
      ],
      yawnMs,
    );
  }

  private fidget(now: number): Reaction | null {
    const { fidgetMinMs, fidgetMaxMs } = this.timing;
    const gap = fidgetMinMs + this.random() * (fidgetMaxMs - fidgetMinMs);
    this.nextFidgetAt = now + gap * this.fidgetFactor();
    const motion = this.pick('fidget', ['look_around', 'yawn', 'nod']);
    if (motion === 'look_around') {
      const ms = this.timing.lookAroundMs;
      return this.react(
        now,
        'fidget',
        'fidget:look_around',
        [
          { atMs: 0, motion },
          { atMs: ms, base: { name: 'idle', interrupt: false } },
        ],
        ms,
      );
    }
    const face: FaceFlash | undefined =
      motion === 'yawn'
        ? { eyes: 'sleepy', mouth: 'small_o', durationMs: clipMs('yawn') }
        : undefined;
    return this.react(now, 'fidget', `fidget:${motion}`, [
      { atMs: 0, motion, ...(face ? { face } : {}) },
    ]);
  }
}
