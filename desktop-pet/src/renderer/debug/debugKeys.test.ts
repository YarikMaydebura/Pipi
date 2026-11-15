import { EyeState } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import {
  calmRequested,
  CLIP_KEYS,
  clipForKey,
  CONTROL_KEYS,
  EYE_STATE_KEYS,
  eyeStateForKey,
  forceFallbackRequested,
  isDebugEnabled,
  MOUTH_CYCLE_KEY,
  nextMouthOverride,
} from './debugKeys';
import { MOUTH_SHAPES } from '../mouth/mouthShapes';
import { isKnownMotion, isLoopMotion } from '../motion/motions';
import { GLB_CLIPS, LOOPING_CLIPS } from '../scene/partNames';

describe('debug keys', () => {
  it('maps one key to every eye state, in protocol order', () => {
    expect(EYE_STATE_KEYS.length).toBe(EyeState.options.length);
    const mapped = [...EYE_STATE_KEYS].map(eyeStateForKey);
    expect(mapped).toEqual(EyeState.options);
  });

  it('ignores other keys', () => {
    expect(eyeStateForKey('a')).toBeUndefined();
    expect(eyeStateForKey('')).toBeUndefined();
    expect(eyeStateForKey('12')).toBeUndefined();
  });

  it('cycles the mouth through every shape and back to auto', () => {
    const seen: (string | null)[] = [];
    let mouth = nextMouthOverride(null);
    while (mouth !== null) {
      seen.push(mouth);
      mouth = nextMouthOverride(mouth);
    }
    expect(seen).toEqual([...MOUTH_SHAPES]);
  });

  it('uses a mouth key that no other debug control uses', () => {
    expect(EYE_STATE_KEYS.includes(MOUTH_CYCLE_KEY)).toBe(false);
    expect(['m', 'M', 'c', 't', 'j', 's']).not.toContain(MOUTH_CYCLE_KEY);
  });

  it('is on in dev, or with ?debug=1', () => {
    expect(isDebugEnabled('', true)).toBe(true);
    expect(isDebugEnabled('', false)).toBe(false);
    expect(isDebugEnabled('?debug=1', false)).toBe(true);
  });

  it('forces the 2D fallback only with ?fallback=1', () => {
    expect(forceFallbackRequested('?fallback=1')).toBe(true);
    expect(forceFallbackRequested('?fallback=0')).toBe(false);
    expect(forceFallbackRequested('')).toBe(false);
  });

  it('has a key for every glb clip, and every clip has a procedural fallback', () => {
    expect(Object.values(CLIP_KEYS).sort()).toEqual([...GLB_CLIPS].sort());
    for (const clip of GLB_CLIPS) {
      expect(clip === 'idle' || isKnownMotion(clip), `${clip} has no fallback`).toBe(true);
    }
    for (const loop of LOOPING_CLIPS) expect(loop === 'idle' || isLoopMotion(loop)).toBe(true);
  });

  it('uses clip keys that clash with no other debug key', () => {
    for (const key of Object.keys(CLIP_KEYS)) {
      expect(key).toHaveLength(1);
      expect(EYE_STATE_KEYS.includes(key)).toBe(false);
      expect(CONTROL_KEYS).not.toContain(key);
    }
    expect(clipForKey('p')).toBe('poke');
    expect(clipForKey('D')).toBe('dance');
    expect(clipForKey('toString')).toBeUndefined();
  });

  it('starts in calm mode only with ?calm=1', () => {
    expect(calmRequested('?calm=1')).toBe(true);
    expect(calmRequested('?calm=0')).toBe(false);
    expect(calmRequested('')).toBe(false);
  });
});
