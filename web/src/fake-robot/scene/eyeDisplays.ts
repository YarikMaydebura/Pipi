// The robot's two round eye displays, showing PIPI's teal eyes (the "same eyes" identity cue).
// Unlike Pipi's transparent eyes, the Alpha Mini's displays are opaque: the shared eye drawer
// paints the eye, then the dark display colour is filled in BEHIND it. "off" = a dark display.
// Contract (alpha_mini.glb, same as pipi.glb): EyeL / EyeR share material "EyeScreen", UVs cover
// the full 0..1 square (glTF V: 0 = top), EyeR is mirrored, so one image drives both eyes.
import { CanvasTexture, DoubleSide, MeshStandardMaterial, SRGBColorSpace } from 'three';
import { drawEye, mirrorForRightEye, type EyeFrame } from '@pipi/shared/look';

export const EYE_DISPLAY_SIZE = 512;
/** The display glass when nothing glows (≈ linear 0.03 / 0.05 / 0.06 in the glb). */
export const DISPLAY_DARK = '#080d0f';
const EYE_GLOW = 1.35; // emissive intensity of the displays

class EyeDisplay {
  readonly texture: CanvasTexture;
  readonly material: MeshStandardMaterial;
  private readonly ctx: CanvasRenderingContext2D;

  constructor(name: string) {
    const canvas = document.createElement('canvas');
    canvas.width = EYE_DISPLAY_SIZE;
    canvas.height = EYE_DISPLAY_SIZE;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2D canvas is not available for the eye displays');
    this.ctx = ctx;
    this.texture = new CanvasTexture(canvas);
    this.texture.colorSpace = SRGBColorSpace;
    this.texture.flipY = false; // glTF UV convention
    this.texture.anisotropy = 4;
    this.material = new MeshStandardMaterial({
      name,
      color: 0x000000,
      map: this.texture,
      emissive: 0xffffff,
      emissiveMap: this.texture,
      emissiveIntensity: EYE_GLOW,
      roughness: 0.18,
      metalness: 0,
      toneMapped: false, // keep the teal saturated
      side: DoubleSide, // like the glb's EyeScreen (doubleSided): the discs' winding varies
    });
  }

  draw(frame: EyeFrame): void {
    const size = EYE_DISPLAY_SIZE;
    drawEye(this.ctx, frame, size);
    // Fill the dark glass behind whatever the eye drawer painted (a soft vignette, not flat).
    this.ctx.save();
    this.ctx.globalCompositeOperation = 'destination-over';
    const glass = this.ctx.createRadialGradient(
      size / 2,
      size / 2,
      0,
      size / 2,
      size / 2,
      size * 0.7,
    );
    glass.addColorStop(0, DISPLAY_DARK);
    glass.addColorStop(1, '#000000');
    this.ctx.fillStyle = glass;
    this.ctx.fillRect(0, 0, size, size);
    this.ctx.restore();
    this.texture.needsUpdate = true;
  }

  dispose(): void {
    this.texture.dispose();
    this.material.dispose();
  }
}

export class EyeDisplays {
  readonly left = new EyeDisplay('EyeScreen (EyeL, live)');
  readonly right = new EyeDisplay('EyeScreen (EyeR, live)');

  draw(frame: EyeFrame): void {
    this.left.draw(frame);
    this.right.draw(mirrorForRightEye(frame));
  }

  /** Extra glow on top of the normal brightness (0 = normal), e.g. for the duel signals. */
  setBoost(extra: number): void {
    this.left.material.emissiveIntensity = EYE_GLOW * (1 + extra);
    this.right.material.emissiveIntensity = EYE_GLOW * (1 + extra);
  }

  dispose(): void {
    this.left.dispose();
    this.right.dispose();
  }
}
