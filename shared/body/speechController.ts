// One `speak` message from start to `speech_done`: shows the caption, plays the audio (or times
// the caption when there is none), drives the talking animation from the audio loudness, and
// reports the real duration when it ends. A new speak interrupts the current one (which then
// reports speech_done right away, so the brain never waits for nothing). stop() is the emergency
// stop: silence and no caption at once, and NO speech_done for the line that was cut.
import type { CaptionView } from './speechBubble';
import type { AudioPlayer, Playback } from './audioPlayer';
import { CAPTION_LINGER_MS, captionDurationMs, smoothLevel, syntheticLevel } from './timing';

export interface SpeakRequest {
  readonly id: string;
  readonly text: string;
  readonly audio_b64?: string | null | undefined;
}

export interface SpeakOutcome {
  readonly ok: boolean;
  readonly error?: string;
}

/** Where the talking animation goes (the current PetView, via PetController). */
export interface TalkOutputs {
  setLevel(level: number): void; // 0..1, every frame while talking
  setTalking(on: boolean): void; // chest light pulse
}

export type FrameScheduler = (callback: (timeMs: number) => void) => () => void;

export interface SpeechControllerDeps {
  readonly player: AudioPlayer;
  readonly caption: CaptionView;
  readonly outputs: TalkOutputs;
  readonly onDone: (refId: string, durationMs: number) => void;
  readonly now?: () => number;
  readonly frame?: FrameScheduler;
}

/** Extra time after the audio's own length before we stop waiting for its `ended` event. */
const PLAYBACK_GUARD_MS = 2000;

interface Utterance {
  readonly id: string;
  readonly start: number;
  playback: Playback | null;
  timer: ReturnType<typeof setTimeout> | undefined;
  stopFrames: (() => void) | undefined;
  finished: boolean;
}

const browserFrames: FrameScheduler = (callback) => {
  const handle = window.requestAnimationFrame(callback);
  return () => window.cancelAnimationFrame(handle);
};

export class SpeechController {
  private current: Utterance | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | undefined;
  private level = 0;
  private readonly now: () => number;
  private readonly frame: FrameScheduler;

  constructor(private readonly deps: SpeechControllerDeps) {
    this.now = deps.now ?? (() => performance.now());
    this.frame = deps.frame ?? browserFrames;
  }

  get speaking(): boolean {
    return this.current !== null && !this.current.finished;
  }

  async speak(request: SpeakRequest): Promise<SpeakOutcome> {
    this.interrupt();
    const utterance: Utterance = {
      id: request.id,
      start: this.now(),
      playback: null,
      timer: undefined,
      stopFrames: undefined,
      finished: false,
    };
    this.current = utterance;
    clearTimeout(this.hideTimer);
    if (request.text.trim()) this.deps.caption.show(request.text);
    this.deps.outputs.setTalking(true);

    let outcome: SpeakOutcome = { ok: true };
    if (request.audio_b64) {
      try {
        const playback = await this.deps.player.play(request.audio_b64);
        if (utterance.finished) {
          playback.stop(); // interrupted while decoding
          return outcome;
        }
        utterance.playback = playback;
        void playback.ended.then(() => this.finish(utterance));
        this.endAfter(utterance, playback.durationMs + PLAYBACK_GUARD_MS);
      } catch (error: unknown) {
        // Cut (stop / a newer line) while decoding: nothing to report, nothing to fall back to.
        if (utterance.finished) return outcome;
        const reason = error instanceof Error ? error.message : String(error);
        console.warn('[pipi] could not play the speech audio, captions only:', reason);
        outcome = { ok: false, error: `audio could not be played (${reason}); captions only` };
      }
    }
    if (utterance.finished) return outcome;
    if (!utterance.playback) this.endAfter(utterance, captionDurationMs(request.text));
    this.animate(utterance);
    return outcome;
  }

  /** Stop speaking now (e.g. Pipi jumps off the screen). The cut line reports speech_done. */
  interrupt(): void {
    const utterance = this.current;
    if (!utterance || utterance.finished) return;
    utterance.playback?.stop();
    this.finish(utterance);
  }

  /**
   * Emergency stop (brain `stop`): the audio ends at once, the caption disappears now (no
   * linger), the talking animation ends, and the cut line never reports speech_done — not now
   * and not later (a line that was still decoding is dropped silently too).
   */
  stop(): void {
    const utterance = this.current;
    if (utterance && !utterance.finished) {
      utterance.playback?.stop();
      this.finish(utterance, false);
    }
    clearTimeout(this.hideTimer);
    this.deps.caption.hide();
  }

  private endAfter(utterance: Utterance, ms: number): void {
    clearTimeout(utterance.timer);
    utterance.timer = setTimeout(() => this.finish(utterance), ms);
  }

  private animate(utterance: Utterance): void {
    let last = this.now();
    const step = (): void => {
      if (utterance.finished) return;
      const now = this.now();
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      const target = utterance.playback
        ? utterance.playback.level()
        : syntheticLevel((now - utterance.start) / 1000);
      this.level = smoothLevel(this.level, target, dt);
      this.deps.outputs.setLevel(this.level);
      utterance.stopFrames = this.frame(step);
    };
    utterance.stopFrames = this.frame(step);
  }

  private finish(utterance: Utterance, report = true): void {
    if (utterance.finished) return;
    utterance.finished = true;
    clearTimeout(utterance.timer);
    utterance.stopFrames?.();
    const durationMs = Math.max(0, Math.round(this.now() - utterance.start));
    if (this.current === utterance) {
      this.level = 0;
      this.deps.outputs.setLevel(0);
      this.deps.outputs.setTalking(false);
      this.hideTimer = setTimeout(() => this.deps.caption.hide(), CAPTION_LINGER_MS);
    }
    if (report) this.deps.onDone(utterance.id, durationMs);
  }
}
