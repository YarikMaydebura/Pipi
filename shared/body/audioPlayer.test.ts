import { afterEach, describe, expect, it, vi } from 'vitest';
import { WebAudioPlayer, type ToneNote } from './audioPlayer';

interface FakeOscillator {
  type: string;
  startedAt: number | null;
  stoppedAt: number | null;
  frequency: number | null;
}

/** Just enough of Web Audio to follow what playTones schedules. */
function installFakeAudio(state: 'running' | 'suspended', failing = false): FakeOscillator[] {
  const oscillators: FakeOscillator[] = [];
  class FakeAudioContext {
    state = state;
    currentTime = 5;
    destination = {};
    resume = async (): Promise<void> => undefined;
    createOscillator(): unknown {
      if (failing) throw new Error('no oscillators today');
      const record: FakeOscillator = {
        type: 'sine',
        startedAt: null,
        stoppedAt: null,
        frequency: null,
      };
      oscillators.push(record);
      return {
        set type(value: string) {
          record.type = value;
        },
        frequency: {
          setValueAtTime: (value: number) => {
            record.frequency = value;
          },
        },
        connect: () => undefined,
        disconnect: () => undefined,
        start: (at: number) => {
          record.startedAt = at;
        },
        stop: (at: number) => {
          record.stoppedAt = at;
        },
        onended: null,
      };
    }
    createGain(): unknown {
      return {
        gain: { setValueAtTime: () => undefined, exponentialRampToValueAtTime: () => undefined },
        connect: () => undefined,
        disconnect: () => undefined,
      };
    }
  }
  vi.stubGlobal('AudioContext', FakeAudioContext);
  return oscillators;
}

const NOTES: readonly ToneNote[] = [
  { frequencyHz: 880, atMs: 0, durationMs: 90, gain: 0.2, wave: 'triangle' },
  { frequencyHz: 1320, atMs: 70, durationMs: 190, gain: 0.2 },
];

describe('WebAudioPlayer.playTones', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('stays silent (and says so) before the page was clicked', () => {
    installFakeAudio('suspended');
    const player = new WebAudioPlayer();
    expect(player.playTones(NOTES)).toBe(false); // no audio context yet: never creates one
  });

  it('stays silent while the audio context is still suspended', async () => {
    const oscillators = installFakeAudio('suspended');
    const player = new WebAudioPlayer();
    expect(await player.unlock()).toBe(false);
    expect(player.playTones(NOTES)).toBe(false);
    expect(oscillators).toHaveLength(0);
  });

  it('schedules every note from "now" once audio is unlocked', async () => {
    const oscillators = installFakeAudio('running');
    const player = new WebAudioPlayer();
    expect(await player.unlock()).toBe(true);
    expect(player.playTones(NOTES)).toBe(true);
    expect(oscillators.map((o) => o.frequency)).toEqual([880, 1320]);
    expect(oscillators.map((o) => o.type)).toEqual(['triangle', 'sine']);
    expect(oscillators[0]?.startedAt).toBe(5); // the first note starts immediately
    expect(oscillators[1]?.startedAt).toBeCloseTo(5.07, 6);
    expect(oscillators[1]?.stoppedAt).toBeGreaterThan(5.26);
  });

  it('never throws: a Web Audio failure only means no sound', async () => {
    installFakeAudio('running', true);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const player = new WebAudioPlayer();
    await player.unlock();
    expect(player.playTones(NOTES)).toBe(false);
    expect(warn).toHaveBeenCalled();
  });
});
