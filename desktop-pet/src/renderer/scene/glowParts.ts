// Emissive accents on the model: cheeks (a soft glow by default, bright when happy), chest
// light (pulses while speaking) and the antenna sprout (always a faint glow). Missing parts are
// simply skipped.
import { Mesh, MeshStandardMaterial, type Material, type Object3D } from 'three';
import type { EyeLook } from '../eyes/eyeFrame';
import { damp } from '../motion/pose';
import { GLOW_PARTS, namesMatch } from './partNames';

type GlowKey = keyof typeof GLOW_PARTS;

/** How the cheeks glow: soft blush by default, bright when happy, dark with the screen off. */
export type CheekMode = 'off' | 'soft' | 'bright';

/** The cheeks that go with the visible eye state. */
export function cheekModeFor(state: EyeLook): CheekMode {
  if (state === 'off') return 'off';
  return state === 'happy' || state === 'love' ? 'bright' : 'soft';
}

// Emissive intensity and (for transparent cheek materials) opacity per mode.
const CHEEK_LOOK: Readonly<Record<CheekMode, { glow: number; opacity: number }>> = {
  off: { glow: 0, opacity: 0 },
  soft: { glow: 0.55, opacity: 0.5 },
  bright: { glow: 1.6, opacity: 0.9 },
};
const CHEST_IDLE = 0.35;
const CHEST_PULSE_MAX = 2.2;
const SPROUT_GLOW = 0.35;
const FADE_RATE = 8;

function findGlowMaterials(model: Object3D, key: GlowKey): MeshStandardMaterial[] {
  const spec = GLOW_PARTS[key];
  const found = new Set<MeshStandardMaterial>();
  model.traverse((object) => {
    if (!(object instanceof Mesh)) return;
    const materials: Material[] = Array.isArray(object.material)
      ? object.material
      : [object.material];
    const meshMatches = spec.meshes.some((name) => namesMatch(object.name, name));
    for (const material of materials) {
      const matches = meshMatches || namesMatch(material.name, spec.material);
      if (matches && material instanceof MeshStandardMaterial) found.add(material);
    }
  });
  for (const material of found) {
    // A glb may export the glow colour only as base colour; glow in that colour then.
    if (material.emissive.getHex() === 0) material.emissive.copy(material.color);
  }
  return [...found];
}

export class GlowParts {
  private readonly cheeks: MeshStandardMaterial[];
  private readonly chest: MeshStandardMaterial[];
  private readonly sprout: MeshStandardMaterial[];
  private cheeksOn = false;
  private chestPulse = false;
  private cheekLevel = CHEEK_LOOK.soft.glow;
  private cheekOpacity = CHEEK_LOOK.soft.opacity;
  private speechLevel = 0;

  constructor(model: Object3D) {
    this.cheeks = findGlowMaterials(model, 'cheek');
    this.chest = findGlowMaterials(model, 'chest');
    this.sprout = findGlowMaterials(model, 'sprout');
  }

  setCheeks(on: boolean): void {
    this.cheeksOn = on;
  }

  setChestPulse(on: boolean): void {
    this.chestPulse = on;
  }

  /** While speaking, the chest light follows the voice's loudness (0..1). */
  setSpeechLevel(level: number): void {
    this.speechLevel = Math.min(1, Math.max(0, level));
  }

  /**
   * `face` describes the expression: 'bright' (happy) or 'off' (screen off) win over the
   * default soft blush; setCheeks(true) also makes them bright unless the screen is off.
   */
  update(t: number, dt: number, face: CheekMode): void {
    const mode: CheekMode = face === 'soft' && this.cheeksOn ? 'bright' : face;
    const target = CHEEK_LOOK[mode];
    this.cheekLevel = damp(this.cheekLevel, target.glow, FADE_RATE, dt);
    this.cheekOpacity = damp(this.cheekOpacity, target.opacity, FADE_RATE, dt);
    for (const m of this.cheeks) {
      m.emissiveIntensity = this.cheekLevel;
      if (m.transparent) m.opacity = this.cheekOpacity;
    }

    const rhythm = this.chestPulse ? 0.5 + 0.5 * Math.sin(t * Math.PI * 2 * 1.6) : 0;
    const pulse = Math.max(rhythm * (this.speechLevel > 0 ? 0.35 : 1), this.speechLevel);
    const chestLevel = CHEST_IDLE + pulse * (CHEST_PULSE_MAX - CHEST_IDLE);
    for (const m of this.chest) m.emissiveIntensity = chestLevel;

    const sproutLevel = SPROUT_GLOW * (0.85 + 0.15 * Math.sin(t * 1.3));
    for (const m of this.sprout) m.emissiveIntensity = sproutLevel;
  }
}
