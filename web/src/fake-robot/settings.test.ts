import { describe, expect, it } from 'vitest';
import { defaultBrainUrl, readSettings, validBrainUrl } from './settings';

describe('page settings', () => {
  it('talks to the brain on the machine that served the page by default', () => {
    expect(readSettings('', '192.168.1.20').brainUrl).toBe('ws://192.168.1.20:8765');
    expect(defaultBrainUrl('')).toBe('ws://127.0.0.1:8765');
    expect(defaultBrainUrl('::1')).toBe('ws://[::1]:8765');
  });

  it('accepts ?brain=ws://host:port for a second machine', () => {
    expect(readSettings('?brain=ws://10.0.0.5:9000', 'localhost').brainUrl).toBe(
      'ws://10.0.0.5:9000',
    );
  });

  it('ignores anything that is not a WebSocket URL', () => {
    expect(validBrainUrl('http://evil.example')).toBeNull();
    expect(validBrainUrl('javascript:alert(1)')).toBeNull();
    expect(validBrainUrl('not a url')).toBeNull();
    expect(readSettings('?brain=http://x', 'localhost').brainUrl).toBe('ws://localhost:8765');
  });

  it('reads the flags', () => {
    expect(readSettings('?awake=1&debug=1', 'h')).toMatchObject({ startAwake: true, debug: true });
    expect(readSettings('?awake=0', 'h')).toMatchObject({ startAwake: false, debug: false });
  });

  it('uses the model clips unless ?clips=0', () => {
    expect(readSettings('', 'h').useClips).toBe(true);
    expect(readSettings('?clips=0', 'h').useClips).toBe(false);
  });

  it('plays the go sound unless ?gosound=0', () => {
    expect(readSettings('', 'h').goSound).toBe(true);
    expect(readSettings('?gosound=1', 'h').goSound).toBe(true);
    expect(readSettings('?gosound=0', 'h').goSound).toBe(false);
  });

  it('reads a start motion and start eyes, ignoring anything that is not a name / eye state', () => {
    expect(readSettings('', 'h')).toMatchObject({ startMotion: null, startEyes: null });
    expect(readSettings('?motion=act_bird&eyes=countdown', 'h')).toMatchObject({
      startMotion: 'act_bird',
      startEyes: 'countdown',
    });
    expect(readSettings('?motion=<b>x</b>&eyes=angry', 'h')).toMatchObject({
      startMotion: null,
      startEyes: null,
    });
  });
});
