// Pure numbers for speaking: caption reading time, loudness → animation level, smoothing.
// The brain uses the same reading-time idea for its speech_done timeout
// (config bodies.caption_s_per_char, a bit longer than ours on purpose).

export const CAPTION_MS_PER_CHAR = 60;
export const MIN_CAPTION_MS = 1500;
export const MAX_CAPTION_MS = 15000;
/** The bubble stays this long after the voice stops, so the last words can still be read. */
export const CAPTION_LINGER_MS = 700;

const SILENT_DBFS = -50;
const LOUD_DBFS = -12;

/** How long a captions-only line is shown (no audio to time it). */
export function captionDurationMs(text: string): number {
  const estimate = text.trim().length * CAPTION_MS_PER_CHAR;
  return Math.min(MAX_CAPTION_MS, Math.max(MIN_CAPTION_MS, estimate));
}

/** Root mean square of audio samples in -1..1. */
export function rms(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const value = samples[i] ?? 0;
    sum += value * value;
  }
  return Math.sqrt(sum / samples.length);
}

/** Loudness → 0..1 animation level (−50 dBFS and below = 0, −12 dBFS and above = 1). */
export function levelFromRms(value: number): number {
  if (value <= 0) return 0;
  const dbfs = 20 * Math.log10(value);
  return Math.min(1, Math.max(0, (dbfs - SILENT_DBFS) / (LOUD_DBFS - SILENT_DBFS)));
}

/** Fast attack, slower release: syllables pop, pauses fade softly. Frame-rate independent. */
export function smoothLevel(current: number, target: number, dtSeconds: number): number {
  const rate = target > current ? 30 : 9;
  return target + (current - target) * Math.exp(-rate * dtSeconds);
}

/** A gentle talking rhythm for captions without audio, so Pipi still looks like it speaks. */
export function syntheticLevel(tSeconds: number): number {
  const syllables = Math.max(0, Math.sin(tSeconds * Math.PI * 2 * 4.2));
  return 0.15 + 0.35 * syllables * (0.75 + 0.25 * Math.sin(tSeconds * 2.3));
}
