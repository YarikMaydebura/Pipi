// Translates brain → body messages into calls on the robot view, speech and caption, and decides
// WHEN each message is acked (the brain client acks once handle() resolves):
// - eyes / motion / caption / body_config / calm: at once (body_config and calm are pet-only and
//   simply acknowledged),
// - speak: once the audio has started (speech_done is sent later by the speech controller),
// - activate: when the wake-up animation has FINISHED; deactivate: when the robot has slumped
//   into its sleep pose and the eyes are off. Both are capped well below the brain's
//   bodies.migration_timeout_s, so a stuck animation can never make the brain wait for nothing.
// - stop (emergency stop): at once. Speech and caption end (no speech_done for the cut line),
//   the running motion is cut, an awake robot rests in idle with idle eyes; it stays awake (a
//   sleeping robot stays asleep).
// The duel eye states (countdown / signal_go) are also reported as a scene cue (onCue), so the
// page can tint the room and play the "go" sound.
// No three.js here: the view is an interface, so all of this is unit-tested with fakes.
import type { BrainToBody, EyeState } from '@pipi/shared';
import type { HandleResult } from '@pipi/shared/body';
import { cueForEyes, type DuelCue } from './duelCue';
import { SLEEP_FADE_S, type BaseLoop } from './motionPlan';

export interface MotionHandle {
  /** Resolves when the motion has finished (or was replaced by another one). */
  readonly finished: Promise<void>;
}

/** What the controller needs from the robot on screen (3D scene or the 2D fallback). */
export interface RobotView {
  setEyes(state: EyeState): void;
  /** 0..1 loudness while speaking: eye glow, chest badge. */
  setSpeechLevel(level: number): void;
  /** The loop to rest in; `interrupt` cuts the running motion (one-shot or held) short. */
  setBase(loop: BaseLoop, interrupt: boolean): void;
  /** Play a named motion (clip or procedural fallback); null if the robot cannot do it. */
  perform(name: string): MotionHandle | null;
}

export interface SpeechService {
  speak(request: {
    readonly id: string;
    readonly text: string;
    readonly audio_b64?: string | null | undefined;
  }): Promise<HandleResult>;
  interrupt(): void;
  /** Emergency stop: silence and no caption at once, no speech_done for the cut line. */
  stop(): void;
}

export interface CaptionService {
  show(text: string): void;
  hide(): void;
}

export type Wait = (ms: number) => Promise<void>;

export interface RobotControllerDeps {
  readonly view: RobotView;
  readonly speech: SpeechService;
  readonly caption: CaptionService;
  readonly startAwake?: boolean;
  readonly wait?: Wait;
  /** Called when the duel cue changes (eyes countdown → 'countdown', signal_go → 'go'). */
  readonly onCue?: (cue: DuelCue) => void;
}

/** activate / deactivate ack at the latest after this (brain waits migration_timeout_s = 8 s). */
export const TRANSITION_CAP_MS = 6000;
/** After the sleep crossfade the slump has settled: eyes off, then ack. */
export const SLEEP_SETTLE_MS = Math.round(SLEEP_FADE_S * 1000) + 300;

const OK: HandleResult = { ok: true };

const realWait: Wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Resting loop that matches the eye state the brain asked for. */
export function restingLoopFor(state: EyeState): BaseLoop {
  if (state === 'listening') return 'listen';
  if (state === 'thinking') return 'think';
  return 'idle';
}

export class RobotController {
  private readonly view: RobotView;
  private readonly speech: SpeechService;
  private readonly caption: CaptionService;
  private readonly wait: Wait;
  private readonly onCue: ((cue: DuelCue) => void) | undefined;
  private cue: DuelCue = 'none';
  private awakeNow: boolean;
  private eyeState: EyeState;
  private talking = false;
  private base: BaseLoop;
  /** Increases on every activate/deactivate: a later one supersedes an earlier one. */
  private transition = 0;

  constructor(deps: RobotControllerDeps) {
    this.view = deps.view;
    this.speech = deps.speech;
    this.caption = deps.caption;
    this.wait = deps.wait ?? realWait;
    this.onCue = deps.onCue;
    this.awakeNow = deps.startAwake ?? false;
    this.eyeState = this.awakeNow ? 'idle' : 'off';
    this.base = this.awakeNow ? 'idle' : 'sleep';
    this.view.setEyes(this.eyeState);
    this.view.setBase(this.base, true);
  }

  get awake(): boolean {
    return this.awakeNow;
  }

  get currentEyes(): EyeState {
    return this.eyeState;
  }

  get currentBase(): BaseLoop {
    return this.base;
  }

  /** Speech started / ended (from the speech controller): talk loop while speaking. */
  setTalking(on: boolean): void {
    this.talking = on;
    this.refreshBase(false);
  }

  setSpeechLevel(level: number): void {
    this.view.setSpeechLevel(level);
  }

  async handle(message: BrainToBody): Promise<HandleResult> {
    switch (message.type) {
      case 'eyes':
        this.setEyes(message.state);
        return OK;
      case 'motion':
        return this.view.perform(message.name)
          ? OK
          : { ok: false, error: `unknown motion: ${message.name}` };
      case 'speak':
        if (this.awakeNow) this.setEyes(message.expression);
        return this.speech.speak(message);
      case 'caption':
        if (message.text === null) this.caption.hide();
        else this.caption.show(message.text);
        return OK;
      case 'activate':
        return this.wake();
      case 'deactivate':
        return this.sleep();
      case 'body_config':
      case 'calm':
        return OK; // desktop-pet settings: nothing to do for a robot
      case 'stop':
        return this.stop();
    }
  }

  /**
   * Emergency stop: everything the robot is doing ends now. Synchronous, so the ack goes out at
   * once. The robot stays active: awake → idle loop + idle eyes, asleep → still asleep.
   */
  private stop(): HandleResult {
    this.speech.stop(); // silence, caption gone, and no speech_done for the cut line
    this.caption.hide();
    this.talking = false;
    this.view.setSpeechLevel(0);
    if (this.awakeNow) this.showEyes('idle');
    this.refreshBase(true); // cuts the running one-shot / acting loop / duel stance
    return OK;
  }

  private setEyes(state: EyeState): void {
    this.showEyes(state);
    this.refreshBase(false);
  }

  /** Put `state` on the eye displays and report the duel cue that goes with it. */
  private showEyes(state: EyeState): void {
    if (state !== 'blink') this.eyeState = state; // blink is a one-shot
    this.view.setEyes(state);
    const cue = cueForEyes(this.eyeState);
    if (cue === this.cue) return;
    this.cue = cue;
    this.onCue?.(cue);
  }

  private refreshBase(interrupt: boolean): void {
    let next: BaseLoop = restingLoopFor(this.eyeState);
    if (!this.awakeNow) next = 'sleep';
    else if (this.talking) next = 'talk';
    if (next === this.base && !interrupt) return;
    this.base = next;
    this.view.setBase(next, interrupt);
  }

  /** Eyes on (drowsy), wake-up motion, then fully awake. Acked when the motion has finished. */
  private async wake(): Promise<HandleResult> {
    if (this.awakeNow) return OK;
    const token = ++this.transition;
    this.awakeNow = true;
    this.showEyes('sleepy');
    // perform first: the wake_up clip starts from the slump, so it blends in seamlessly; the
    // idle base set afterwards only shows once wake_up has finished.
    const handle = this.view.perform('wake_up');
    this.base = 'idle';
    this.view.setBase('idle', handle === null);
    await this.capped(handle?.finished ?? Promise.resolve());
    if (token === this.transition) this.setEyes('idle');
    return OK;
  }

  /** Stop talking, slump into the sleep loop, eyes off. Acked when the slump has settled. */
  private async sleep(): Promise<HandleResult> {
    if (!this.awakeNow) return OK;
    const token = ++this.transition;
    this.awakeNow = false;
    this.speech.interrupt();
    this.caption.hide();
    this.showEyes('sleepy');
    this.refreshBase(true);
    await this.wait(SLEEP_SETTLE_MS);
    if (token === this.transition) this.showEyes('off');
    return OK;
  }

  private async capped(finished: Promise<void>): Promise<void> {
    await Promise.race([finished, this.wait(TRANSITION_CAP_MS)]);
  }
}
