import { BrainToBody, EyeState } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import { ONE_SHOT_CLIPS, HELD_MOTIONS, planMotion } from '../motionPlan';
import { debugMessage, EYE_KEYS, MOTION_KEYS, STOP_KEY } from './debugKeys';

const NO_CLIPS = (): boolean => false;

describe('debug keys', () => {
  it('maps keys to valid brain messages', () => {
    expect(debugMessage('w')).toEqual({ type: 'activate', entrance: 'wake_up' });
    expect(debugMessage('s')).toEqual({ type: 'deactivate', exit: 'sleep' });
    expect(debugMessage('v')).toEqual({ type: 'motion', name: 'signature_wave' });
    expect(debugMessage('1')).toEqual({ type: 'eyes', state: 'idle' });
    expect(debugMessage('=')).toEqual({ type: 'eyes', state: 'signal_go' });
    expect(debugMessage('Z')).toBeNull();
    expect(debugMessage('toString')).toBeNull();
    for (const key of ['w', 's', 't', 'n', '5', STOP_KEY, ...Object.keys(MOTION_KEYS)]) {
      expect(BrainToBody.safeParse({ ...debugMessage(key), id: 'x', ts: 1 }).success, key).toBe(
        true,
      );
    }
  });

  it('has a key for every eye state: - is countdown and = is signal_go (the duel signals)', () => {
    expect(EYE_KEYS.map((key) => debugMessage(key))).toEqual(
      EyeState.options.map((state) => ({ type: 'eyes', state })),
    );
    expect(debugMessage('-')).toEqual({ type: 'eyes', state: 'countdown' });
  });

  it('Escape is the emergency stop', () => {
    expect(debugMessage('Escape')).toEqual({ type: 'stop' });
  });

  it('has one key for every game motion and every one-shot clip except wake_up', () => {
    const bound = Object.values(MOTION_KEYS);
    expect(new Set(bound).size).toBe(bound.length);
    for (const name of [...HELD_MOTIONS, ...ONE_SHOT_CLIPS.filter((clip) => clip !== 'wake_up')]) {
      expect(bound, name).toContain(name);
    }
  });

  it('binds only motions the robot can play, on keys nothing else uses', () => {
    for (const [key, name] of Object.entries(MOTION_KEYS)) {
      expect(planMotion(name, NO_CLIPS).kind, name).toBe('procedural');
      expect(key).toHaveLength(1);
      expect(['w', 's', 't', ...EYE_KEYS]).not.toContain(key);
    }
  });
});
