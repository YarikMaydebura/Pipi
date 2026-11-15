import { BrainToBody } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import { debugMessage } from './debugKeys';

describe('debug keys', () => {
  it('maps keys to valid brain messages', () => {
    expect(debugMessage('w')).toEqual({ type: 'activate', entrance: 'wake_up' });
    expect(debugMessage('s')).toEqual({ type: 'deactivate', exit: 'sleep' });
    expect(debugMessage('v')).toEqual({ type: 'motion', name: 'signature_wave' });
    expect(debugMessage('1')).toEqual({ type: 'eyes', state: 'idle' });
    expect(debugMessage('=')).toEqual({ type: 'eyes', state: 'signal_go' });
    expect(debugMessage('z')).toBeNull();
    for (const key of ['w', 's', 't', 'n', '5']) {
      expect(BrainToBody.safeParse({ ...debugMessage(key), id: 'x', ts: 1 }).success).toBe(true);
    }
  });
});
