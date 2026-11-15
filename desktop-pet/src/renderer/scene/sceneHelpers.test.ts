import { describe, expect, it } from 'vitest';
import { dataUrlToArrayBuffer } from './dataUrl';
import { cheekModeFor } from './glowParts';
import { MOUTH_MATERIAL_NAME, MOUTH_NAME, namesMatch, normalizeName } from './partNames';

describe('part names', () => {
  it('matches Blender names after glTF export sanitising', () => {
    expect(namesMatch('shoulderL', 'shoulder.L')).toBe(true); // GLTFLoader drops the dot
    expect(namesMatch('shoulder_L', 'shoulder.L')).toBe(true);
    expect(namesMatch('Head.001', 'head')).toBe(true);
    expect(namesMatch('EyeR001', 'EyeR')).toBe(true);
    expect(namesMatch('antenna_base', 'antenna_base')).toBe(true);
  });

  it('keeps different parts apart', () => {
    expect(namesMatch('shoulder.R', 'shoulder.L')).toBe(false);
    expect(namesMatch('EyeL', 'EyeR')).toBe(false);
    expect(normalizeName('antenna_tip')).not.toBe(normalizeName('antenna_base'));
  });
});

describe('dataUrlToArrayBuffer', () => {
  it('decodes base64 data URLs', () => {
    const bytes = new Uint8Array(dataUrlToArrayBuffer('data:model/gltf-binary;base64,Z2xURg=='));
    expect(Array.from(bytes)).toEqual([0x67, 0x6c, 0x54, 0x46]); // "glTF"
  });

  it('decodes percent-encoded data URLs', () => {
    const bytes = new Uint8Array(dataUrlToArrayBuffer('data:text/plain,hi%21'));
    expect(new TextDecoder().decode(bytes)).toBe('hi!');
  });

  it('rejects anything that is not a data URL', () => {
    expect(() => dataUrlToArrayBuffer('file:///pipi.glb')).toThrow();
  });
});

describe('cheekModeFor', () => {
  it('blushes softly by default, brightly when happy, not at all when the screen is off', () => {
    expect(cheekModeFor('idle')).toBe('soft');
    expect(cheekModeFor('listening')).toBe('soft');
    expect(cheekModeFor('happy')).toBe('bright');
    expect(cheekModeFor('off')).toBe('off');
  });
});

describe('mouth names', () => {
  it('keeps the Mouth mesh and its MouthScreen material apart from the eyes', () => {
    expect(namesMatch('Mouth', MOUTH_NAME)).toBe(true);
    expect(namesMatch('MouthScreen.001', MOUTH_MATERIAL_NAME)).toBe(true);
    expect(namesMatch(MOUTH_NAME, 'EyeL')).toBe(false);
    expect(namesMatch(MOUTH_MATERIAL_NAME, 'EyeScreen')).toBe(false);
  });
});
