// Names the Blender model (pipi.glb) and the procedural placeholder share.
// The contract is documented in docs/SYSTEM_DESIGN.md §5.

/** Bones the pet animates procedurally (look-at, idle life, fallback motions). */
export const BONE_NAMES = {
  root: 'root',
  hips: 'hips',
  spine: 'spine',
  head: 'head',
  antennaBase: 'antenna_base',
  antennaTip: 'antenna_tip',
  shoulderL: 'shoulder.L',
  shoulderR: 'shoulder.R',
  elbowL: 'elbow.L',
  elbowR: 'elbow.R',
} as const;

export type BoneKey = keyof typeof BONE_NAMES;

export const EYE_L_NAME = 'EyeL';
export const EYE_R_NAME = 'EyeR';
export const EYE_MATERIAL_NAME = 'EyeScreen';
export const MOUTH_NAME = 'Mouth';
export const MOUTH_MATERIAL_NAME = 'MouthScreen';

/** Emissive accents: mesh names and material names (either one is enough to find them). */
export const GLOW_PARTS = {
  cheek: { meshes: ['CheekL', 'CheekR'], material: 'Cheek' },
  chest: { meshes: ['ChestLight'], material: 'ChestLight' },
  sprout: { meshes: ['Sprout'], material: 'Sprout' },
} as const;

/** Looping clips repeat until replaced; the others play once (24 fps in the Blender file). */
export const LOOPING_CLIPS: readonly string[] = [
  'idle',
  'talk',
  'think',
  'sleep',
  'listen',
  'dance',
  'look_around',
  'dangle',
];
/** One-shot clips: they play once, then Pipi returns to its current base loop. */
export const ONE_SHOT_CLIPS: readonly string[] = [
  'happy',
  'signature_wave',
  'jump_out',
  'jump_in',
  'nod',
  'shake_head',
  'poke',
  'giggle',
  'spin',
  'shy',
  'surprised',
  'yawn',
  'land',
  'celebrate',
  'love',
];
/** Every clip pipi.glb is expected to contain (docs/SYSTEM_DESIGN.md §5). */
export const GLB_CLIPS: readonly string[] = [...LOOPING_CLIPS, ...ONE_SHOT_CLIPS];
/** One-shot clips after which Pipi does NOT go back to idle (it stays off-screen / asleep). */
export const HOLD_CLIPS: readonly string[] = ['jump_out'];

/**
 * Compare names the way Blender/glTF exports them: case-insensitive, ignoring separators
 * ("shoulder.L" becomes "shoulderL" in three.js) and a duplicate suffix such as ".001".
 */
export function normalizeName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[._]?\d{3}$/, '')
    .replace(/[\s._\-:/]/g, '');
}

export function namesMatch(actual: string, wanted: string): boolean {
  return normalizeName(actual) === normalizeName(wanted);
}
