// Translates brain → body protocol messages into calls on the current PetView and the pet's
// services (speech, caption bubble, migration). The WebSocket client (link/brainClient.ts)
// passes every validated message to handle(); the returned result becomes the `ack`.
// Ack timing: most messages are acked at once; `activate` / `deactivate` are acked when their
// animation has FINISHED, and `speak` once the audio has started (speech_done comes later).
// It also tells the interaction layer what the brain is doing (BrainActivity), so the pet's
// own reactions never fight brain commands, and it is the ReactionTarget those reactions use.
import type { BrainToBody, EyeState, RobotSide } from '@pipi/shared';
import type { ReactionTarget } from '../interaction/interactionController';
import type { BrainActivity } from '../interaction/reactionPolicy';
import type { MouthShape } from '../mouth/mouthShapes';
import type { FaceFlash, PetView } from './PetView';

export interface HandleResult {
  readonly ok: boolean;
  readonly error?: string;
}

/** Speech: caption + audio + talking animation (speech/speechController.ts). */
export interface SpeechService {
  speak(request: {
    readonly id: string;
    readonly text: string;
    readonly audio_b64?: string | null | undefined;
  }): Promise<HandleResult>;
  interrupt(): void;
}

/** The speech bubble (speech/speechBubble.ts). */
export interface CaptionService {
  show(text: string): void;
  hide(): void;
}

/** Jumping off / onto the screen (migration/migrator.ts). */
export interface MigrationService {
  setRobotSide(side: RobotSide): Promise<void>;
  jumpOut(): Promise<void>;
  jumpIn(): Promise<void>;
  fadeOut(): Promise<void>;
  fadeIn(): Promise<void>;
  appear(): Promise<void>;
}

export interface PetServices {
  readonly speech?: SpeechService;
  readonly caption?: CaptionService;
  readonly migration?: MigrationService;
}

/** Told about every brain message: the activity after it, and the motion name if one played. */
export type BrainActivityListener = (activity: BrainActivity, motion?: string) => void;

/** Body states the brain controls directly (on top of speaking / eye-driven activity). */
type BodyMode = 'normal' | 'asleep' | 'migrating' | 'away';

const OK: HandleResult = { ok: true };

function failure(what: string, error: unknown): HandleResult {
  const reason = error instanceof Error ? error.message : String(error);
  console.warn(`[pipi] ${what} failed:`, reason);
  return { ok: false, error: `${what} failed: ${reason}` };
}

export class PetController implements ReactionTarget {
  private view: PetView;
  private eyeState: EyeState = 'idle';
  private cheeks = false;
  private chestPulse = false;
  private mouthOverride: MouthShape | null = null;
  private services: PetServices;
  private baseMotion = 'idle';
  private dozing = false;
  private speaking = false;
  private eyeActivity: BrainActivity = 'idle';
  private mode: BodyMode = 'normal';
  private listener: BrainActivityListener | null = null;

  constructor(view: PetView, services: PetServices = {}) {
    this.view = view;
    this.services = services;
  }

  /** Plug in the services once they exist (they need the controller themselves). */
  setServices(services: PetServices): void {
    this.services = services;
  }

  /** Swap the view (e.g. 3D → 2D fallback after a WebGL failure) without losing state. */
  replaceView(view: PetView): void {
    this.view.dispose();
    this.view = view;
    view.setEyeState(this.dozing ? 'sleepy' : this.eyeState);
    view.setBaseMotion(this.baseMotion, true);
    view.setCheeks(this.cheeks);
    view.setChestPulse(this.chestPulse);
    view.setMouthOverride(this.mouthOverride);
  }

  get currentView(): PetView {
    return this.view;
  }

  get currentEyeState(): EyeState {
    return this.eyeState;
  }

  setEyeState(state: EyeState): void {
    if (state !== 'blink') this.eyeState = state; // blink is a one-shot action
    this.view.setEyeState(state);
  }

  /** The interaction layer listens here (one listener). */
  setActivityListener(listener: BrainActivityListener | null): void {
    this.listener = listener;
  }

  /** What the brain is making Pipi do right now. */
  get activity(): BrainActivity {
    if (this.mode !== 'normal') return this.mode;
    return this.speaking ? 'speaking' : this.eyeActivity;
  }

  /** Speech started / ended (from the speech controller): chest light + talking activity. */
  setTalking(on: boolean): void {
    this.setChestPulse(on);
    if (on === this.speaking) return;
    const before = this.activity;
    this.speaking = on;
    if (this.activity !== before) this.listener?.(this.activity);
  }

  // --- ReactionTarget: the pet's own reactions (interaction/) ----------------------------------

  setBaseMotion(name: string, interrupt: boolean): void {
    this.baseMotion = name;
    if (!this.view.setBaseMotion(name, interrupt)) {
      console.warn(`[pipi] no loop called ${name}; staying in the current one`);
    }
  }

  flashFace(face: FaceFlash | null): void {
    this.view.flashFace(face);
  }

  /** Idle sleep: sleepy eyes without forgetting the eye state the brain asked for. */
  setDozing(on: boolean): void {
    if (on === this.dozing) return;
    this.dozing = on;
    this.view.setEyeState(on ? 'sleepy' : this.eyeState);
  }

  setCheeks(on: boolean): void {
    this.cheeks = on;
    this.view.setCheeks(on);
  }

  setChestPulse(on: boolean): void {
    this.chestPulse = on;
    this.view.setChestPulse(on);
  }

  /** Debug only: force a mouth shape (null = follow the eye state). */
  setMouthOverride(shape: MouthShape | null): void {
    this.mouthOverride = shape;
    this.view.setMouthOverride(shape);
  }

  /** Talking animation level 0..1 (not remembered: it changes every frame while speaking). */
  setSpeechLevel(level: number): void {
    this.view.setSpeechLevel(level);
  }

  playMotion(name: string): HandleResult {
    return this.view.playMotion(name) ? OK : { ok: false, error: `unknown motion: ${name}` };
  }

  async handle(message: BrainToBody): Promise<HandleResult> {
    switch (message.type) {
      case 'eyes':
        this.dozing = false; // the brain's eyes win over the idle-sleep face
        this.setEyeState(message.state);
        if (message.state !== 'blink') this.eyeActivity = activityForEyes(message.state);
        this.listener?.(this.activity);
        return OK;
      case 'motion': {
        const result = this.playMotion(message.name);
        this.listener?.(this.activity, message.name);
        return result;
      }
      case 'speak':
        this.dozing = false;
        this.setEyeState(message.expression);
        this.listener?.(this.activity);
        return this.services.speech ? this.services.speech.speak(message) : OK;
      case 'caption':
        if (message.text === null) this.services.caption?.hide();
        else this.services.caption?.show(message.text);
        return OK;
      case 'body_config':
        return this.run('placing Pipi on the robot side', () =>
          this.services.migration?.setRobotSide(message.robot_side),
        );
      case 'activate':
        return this.activate(message.entrance);
      case 'deactivate':
        return this.deactivate(message.exit);
    }
  }

  private setMode(mode: BodyMode): void {
    this.mode = mode;
    this.listener?.(this.activity);
  }

  private async activate(entrance: 'jump_in' | 'wake_up' | 'fade_in'): Promise<HandleResult> {
    this.dozing = false;
    this.setEyeState('idle');
    this.eyeActivity = 'idle';
    this.setMode('migrating');
    const migration = this.services.migration;
    let result: HandleResult;
    if (entrance === 'wake_up' || !migration) {
      result = await this.run('showing Pipi', () => migration?.appear());
      this.view.playMotion(entrance === 'wake_up' ? 'wake_up' : 'jump_in');
    } else {
      result =
        entrance === 'jump_in'
          ? await this.run('jump_in', () => migration.jumpIn())
          : await this.run('fade_in', () => migration.fadeIn());
    }
    this.setMode('normal');
    return result;
  }

  private async deactivate(exit: 'jump_out' | 'sleep' | 'fade_out'): Promise<HandleResult> {
    this.dozing = false;
    if (exit === 'sleep') {
      this.view.playMotion('sleep');
      this.setEyeState('sleepy');
      this.setMode('asleep');
      return OK;
    }
    this.setMode('migrating'); // before the speech stops, so nothing reacts to that
    this.services.speech?.interrupt();
    this.services.caption?.hide();
    const migration = this.services.migration;
    if (!migration) {
      this.view.playMotion('jump_out');
      this.setMode('away');
      return OK;
    }
    const result =
      exit === 'jump_out'
        ? await this.run('jump_out', () => migration.jumpOut())
        : await this.run('fade_out', () => migration.fadeOut());
    this.setMode(result.ok ? 'away' : 'normal'); // a failed exit leaves Pipi on screen
    return result;
  }

  private async run(what: string, task: () => Promise<void> | undefined): Promise<HandleResult> {
    try {
      await task();
      return OK;
    } catch (error: unknown) {
      return failure(what, error);
    }
  }
}

/** Eye states that mean the brain is busy with the user (the pet must not fidget then). */
function activityForEyes(state: EyeState): BrainActivity {
  if (state === 'listening') return 'listening';
  if (state === 'thinking') return 'thinking';
  return 'idle';
}
