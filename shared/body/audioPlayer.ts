// Plays the brain's TTS audio (base64 WAV) with Web Audio and measures its loudness live, so
// the eyes, chest light and head can move with the voice.
import { base64ToArrayBuffer } from './base64';
import { levelFromRms, rms } from './timing';

export interface Playback {
  readonly durationMs: number;
  /** Resolves when the audio has ended (or was stopped). */
  readonly ended: Promise<void>;
  /** Current loudness as an animation level 0..1. */
  level(): number;
  stop(): void;
}

/** One synthesised note: a short sine/triangle beep with a soft attack and release. */
export interface ToneNote {
  readonly frequencyHz: number;
  /** Start, in ms after playTones() was called. */
  readonly atMs: number;
  readonly durationMs: number;
  /** Peak gain 0..1 (keep signals well below speech level). */
  readonly gain: number;
  readonly wave?: 'sine' | 'triangle' | 'square';
}

const TONE_ATTACK_S = 0.008;
const TONE_SILENT = 0.0001; // exponential ramps cannot reach 0

export interface AudioPlayer {
  /** Decode and start playing; rejects if the audio cannot be decoded or played. */
  play(audioB64: string): Promise<Playback>;
}

const ANALYSER_SIZE = 1024; // ~21 ms at 48 kHz: one animation frame of audio
/**
 * A browser tab may only start audio after the user clicked it (autoplay policy); until then
 * resume() stays pending. Give up after this long so `speak` is refused quickly and the brain
 * plays the line on the laptop speaker instead of waiting.
 */
export const RESUME_TIMEOUT_MS = 800;

export class WebAudioPlayer implements AudioPlayer {
  private context: AudioContext | null = null;

  /** True once audio may play (always in Electron; after a click/key press in a browser tab). */
  get unlocked(): boolean {
    return this.context?.state === 'running';
  }

  /** Call from a click / key handler: creates and resumes the audio context. */
  async unlock(): Promise<boolean> {
    this.context ??= new AudioContext();
    if (this.context.state === 'suspended') await this.context.resume();
    return this.unlocked;
  }

  /**
   * Play a few synthesised notes (signal sounds such as the duel's "go"): generated with
   * oscillators, so there is no file to load. Never waits and never throws: returns false (and
   * stays silent) when audio is not unlocked yet or Web Audio fails.
   */
  playTones(notes: readonly ToneNote[]): boolean {
    const context = this.context;
    if (!context || context.state !== 'running') return false;
    try {
      const start = context.currentTime;
      for (const note of notes) {
        const from = start + note.atMs / 1000;
        const to = from + note.durationMs / 1000;
        const oscillator = context.createOscillator();
        oscillator.type = note.wave ?? 'sine';
        oscillator.frequency.setValueAtTime(note.frequencyHz, from);
        const gain = context.createGain();
        gain.gain.setValueAtTime(TONE_SILENT, from);
        gain.gain.exponentialRampToValueAtTime(
          Math.max(TONE_SILENT, note.gain),
          from + TONE_ATTACK_S,
        );
        gain.gain.exponentialRampToValueAtTime(TONE_SILENT, to);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.onended = () => {
          oscillator.disconnect();
          gain.disconnect();
        };
        oscillator.start(from);
        oscillator.stop(to + 0.02);
      }
      return true;
    } catch (error: unknown) {
      console.warn('[pipi] could not play a signal sound:', error);
      return false;
    }
  }

  async play(audioB64: string): Promise<Playback> {
    this.context ??= new AudioContext();
    const context = this.context;
    if (context.state === 'suspended') await resumeWithin(context, RESUME_TIMEOUT_MS);
    const buffer = await context.decodeAudioData(base64ToArrayBuffer(audioB64));

    const source = context.createBufferSource();
    source.buffer = buffer;
    const analyser = context.createAnalyser();
    analyser.fftSize = ANALYSER_SIZE;
    source.connect(analyser);
    analyser.connect(context.destination);
    const samples = new Float32Array(analyser.fftSize);

    const ended = new Promise<void>((resolve) => {
      source.onended = () => {
        source.disconnect();
        analyser.disconnect();
        resolve();
      };
    });
    source.start();

    return {
      durationMs: Math.round(buffer.duration * 1000),
      ended,
      level: () => {
        analyser.getFloatTimeDomainData(samples);
        return levelFromRms(rms(samples));
      },
      stop: () => {
        try {
          source.stop();
        } catch {
          // already stopped
        }
      },
    };
  }
}

async function resumeWithin(context: AudioContext, ms: number): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () => reject(new Error('audio is blocked until the page is clicked once')),
      ms,
    );
  });
  try {
    await Promise.race([context.resume(), timeout]);
  } finally {
    clearTimeout(timer);
  }
}
