// Live mouth texture for the 3D model: replaces the glb's "MouthScreen" material on the
// "Mouth" mesh with a canvas-backed material that glows exactly like the eyes.
import { CanvasTexture, MeshStandardMaterial, SRGBColorSpace } from 'three';
import { drawMouth } from './drawMouth';
import { sameMouthFrame, type MouthFrame } from './mouthFrame';

/** The mouth is small on screen, so a smaller canvas than the eyes is plenty. */
export const MOUTH_TEXTURE_SIZE = 256;

export class MouthTexture {
  readonly texture: CanvasTexture;
  readonly material: MeshStandardMaterial;
  private readonly ctx: CanvasRenderingContext2D;
  private last: MouthFrame | null = null;

  constructor() {
    const canvas = document.createElement('canvas');
    canvas.width = MOUTH_TEXTURE_SIZE;
    canvas.height = MOUTH_TEXTURE_SIZE;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2D canvas is not available for the mouth texture');
    this.ctx = ctx;

    this.texture = new CanvasTexture(canvas);
    this.texture.colorSpace = SRGBColorSpace;
    this.texture.flipY = false; // glTF UV convention: v = 0 is the top of the image
    this.texture.anisotropy = 4;

    // Same settings as the eye material (eyes/eyeTextures.ts): pure light, no tone mapping.
    this.material = new MeshStandardMaterial({
      name: 'MouthScreen (live)',
      color: 0x000000,
      map: this.texture,
      emissive: 0xffffff,
      emissiveMap: this.texture,
      emissiveIntensity: 1.25,
      roughness: 0.15,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
    });
  }

  /** Repaint only when the mouth actually changed (it is static most of the time). */
  draw(frame: MouthFrame): void {
    if (sameMouthFrame(this.last, frame)) return;
    this.last = frame;
    drawMouth(this.ctx, frame, MOUTH_TEXTURE_SIZE);
    this.texture.needsUpdate = true;
  }

  dispose(): void {
    this.texture.dispose();
    this.material.dispose();
  }
}
