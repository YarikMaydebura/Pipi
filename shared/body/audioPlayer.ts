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
