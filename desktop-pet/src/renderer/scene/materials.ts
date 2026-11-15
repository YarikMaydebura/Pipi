// Materials for the procedural placeholder (the Blender model brings its own PBR materials).
// Names match the glb so GlowParts and the eye setup find them the same way.
import { MeshPhysicalMaterial, MeshStandardMaterial } from 'three';

export const PIPI_COLORS = {
  shell: 0xe8f5ee, // mint-cream plastic
  belly: 0x5e7f7a, // belly panel, boots
  face: 0x0b1316, // dark glossy face screen
  eye: 0x3fe0c5, // warm teal
  cheek: 0xff8a7a, // coral
  sprout: 0x8fdc7a, // leaf green
} as const;

export interface RobotMaterials {
  readonly shell: MeshPhysicalMaterial;
  readonly belly: MeshPhysicalMaterial;
  readonly face: MeshPhysicalMaterial;
  readonly eyePlaceholder: MeshStandardMaterial;
  readonly mouthPlaceholder: MeshStandardMaterial;
  readonly cheek: MeshStandardMaterial;
  readonly chestLight: MeshStandardMaterial;
  readonly sprout: MeshStandardMaterial;
}

export function createRobotMaterials(): RobotMaterials {
  return {
    shell: new MeshPhysicalMaterial({
      name: 'Shell',
      color: PIPI_COLORS.shell,
      roughness: 0.38,
      clearcoat: 0.55,
      clearcoatRoughness: 0.25,
      sheen: 0.3,
      sheenColor: 0xffffff,
    }),
    belly: new MeshPhysicalMaterial({
      name: 'BellyPanel',
      color: PIPI_COLORS.belly,
      roughness: 0.45,
      clearcoat: 0.3,
    }),
    face: new MeshPhysicalMaterial({
      name: 'FaceScreen',
      color: PIPI_COLORS.face,
      roughness: 0.25,
      clearcoat: 0.6,
      clearcoatRoughness: 0.18,
      // Softer studio reflections: a sharp light-box reflection mid-face read like a nose.
      envMapIntensity: 0.35,
    }),
    // Replaced at runtime by the live eye material (same path as for pipi.glb).
    eyePlaceholder: new MeshStandardMaterial({ name: 'EyeScreen', color: 0x000000 }),
    // Replaced at runtime by the live mouth material.
    mouthPlaceholder: new MeshStandardMaterial({ name: 'MouthScreen', color: 0x000000 }),
    cheek: new MeshStandardMaterial({
      name: 'Cheek',
      color: PIPI_COLORS.cheek,
      emissive: PIPI_COLORS.cheek,
      emissiveIntensity: 0,
      roughness: 0.4,
      transparent: true,
      opacity: 0.85,
    }),
    chestLight: new MeshStandardMaterial({
      name: 'ChestLight',
      color: PIPI_COLORS.eye,
      emissive: PIPI_COLORS.eye,
      emissiveIntensity: 0.35,
      roughness: 0.2,
    }),
    sprout: new MeshStandardMaterial({
      name: 'Sprout',
      color: PIPI_COLORS.sprout,
      emissive: PIPI_COLORS.sprout,
      emissiveIntensity: 0.35,
      roughness: 0.5,
    }),
  };
}
