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

export class WebAudioPlayer implements AudioPlayer {
  private context: AudioContext | null = null;

  async play(audioB64: string): Promise<Playback> {
    this.context ??= new AudioContext();
    const context = this.context;
    if (context.state === 'suspended') await context.resume();
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
