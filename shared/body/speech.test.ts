import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AudioPlayer, Playback } from './audioPlayer';
import { base64ToArrayBuffer } from './base64';
import { SpeechController } from './speechController';
import {
  CAPTION_LINGER_MS,
  captionDurationMs,
  levelFromRms,
  MAX_CAPTION_MS,
  MIN_CAPTION_MS,
  rms,
  smoothLevel,
} from './timing';

describe('speech timing', () => {
  it('estimates caption time from the text length, within limits', () => {
    expect(captionDurationMs('hi')).toBe(MIN_CAPTION_MS);
    expect(captionDurationMs('x'.repeat(50))).toBe(3000);
    expect(captionDurationMs('x'.repeat(5000))).toBe(MAX_CAPTION_MS);
  });

  it('maps loudness to an animation level', () => {
    expect(rms([])).toBe(0);
    expect(rms([0.5, -0.5])).toBeCloseTo(0.5);
    expect(levelFromRms(0)).toBe(0);
    expect(levelFromRms(0.001)).toBe(0); // -60 dBFS: silence
    expect(levelFromRms(0.5)).toBe(1); // -6 dBFS: loud
    const mid = levelFromRms(0.03); // about -30 dBFS
    expect(mid).toBeGreaterThan(0.4);
    expect(mid).toBeLessThan(0.7);
  });

  it('rises faster than it falls', () => {
    const up = smoothLevel(0, 1, 0.05);
    const down = 1 - smoothLevel(1, 0, 0.05);
    expect(up).toBeGreaterThan(down);
  });

  it('decodes base64 audio', () => {
    const bytes = new Uint8Array(base64ToArrayBuffer('UklGRg=='));
    expect(String.fromCharCode(...bytes)).toBe('RIFF');
  });
});

interface Harness {
  readonly controller: SpeechController;
  readonly log: string[];
  readonly done: [string, number][];
  readonly endAudio: () => void;
  readonly frames: (() => void)[];
}

function setup(options: { failPlay?: boolean; durationMs?: number } = {}): Harness {
  const log: string[] = [];
  const done: [string, number][] = [];
  const frames: (() => void)[] = [];
  let endAudio = (): void => undefined;
  const player: AudioPlayer = {
    play: async () => {
      if (options.failPlay) throw new Error('cannot decode');
      log.push('play');
      const ended = new Promise<void>((resolve) => {
        endAudio = resolve;
      });
      const playback: Playback = {
        durationMs: options.durationMs ?? 2000,
        ended,
        level: () => 0.8,
        stop: () => {
          log.push('stop');
          endAudio();
        },
      };
      return playback;
    },
  };
  const controller = new SpeechController({
    player,
    caption: { show: (text) => log.push(`show:${text}`), hide: () => log.push('hide') },
    outputs: {
      setLevel: (level) => log.push(level === 0 ? 'level:0' : 'level:>0'),
      setTalking: (on) => log.push(`talking:${on}`),
    },
    onDone: (id, ms) => done.push([id, ms]),
    now: () => Date.now(),
    frame: (callback) => {
      frames.push(() => callback(Date.now()));
      return () => undefined;
    },
  });
  return { controller, log, done, endAudio: () => endAudio(), frames };
}

const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

describe('SpeechController', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('plays audio with caption and talking animation, then reports speech_done', async () => {
    const h = setup();
    const result = await h.controller.speak({ id: 's1', text: 'Hello!', audio_b64: 'UklGRg==' });
    expect(result.ok).toBe(true);
    expect(h.log).toEqual(['show:Hello!', 'talking:true', 'play']);
    vi.advanceTimersByTime(16); // one animation frame later
    h.frames.shift()?.();
    expect(h.log).toContain('level:>0');
    vi.advanceTimersByTime(1184);
    h.endAudio();
    await flush();
    expect(h.done).toEqual([['s1', 1200]]);
    expect(h.log.slice(-2)).toEqual(['level:0', 'talking:false']);
    vi.advanceTimersByTime(CAPTION_LINGER_MS);
    expect(h.log.at(-1)).toBe('hide');
  });

  it('times a captions-only line by its length', async () => {
    const h = setup();
    await h.controller.speak({ id: 's2', text: 'x'.repeat(50) });
    expect(h.log).not.toContain('play');
    vi.advanceTimersByTime(2999);
    expect(h.done).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(h.done).toEqual([['s2', 3000]]);
  });

  it('falls back to captions only when the audio cannot be played, and says so in the ack', async () => {
    const h = setup({ failPlay: true });
    const result = await h.controller.speak({ id: 's3', text: 'Hi', audio_b64: 'bad' });
    expect(result.ok).toBe(false);
    expect(result.error).toContain('captions only');
    vi.advanceTimersByTime(MIN_CAPTION_MS);
    expect(h.done).toEqual([['s3', MIN_CAPTION_MS]]);
  });

  it('a new line interrupts the current one, which still reports speech_done', async () => {
    const h = setup();
    await h.controller.speak({ id: 'a', text: 'first', audio_b64: 'UklGRg==' });
    vi.advanceTimersByTime(300);
    await h.controller.speak({ id: 'b', text: 'second', audio_b64: 'UklGRg==' });
    expect(h.done).toEqual([['a', 300]]);
    expect(h.log).toContain('stop');
    expect(h.controller.speaking).toBe(true);
  });

  it('gives up waiting for the audio end after its length plus a guard', async () => {
    const h = setup({ durationMs: 1000 });
    await h.controller.speak({ id: 'g', text: 'stuck', audio_b64: 'UklGRg==' });
    vi.advanceTimersByTime(3000);
    expect(h.done).toEqual([['g', 3000]]);
  });
});
