// Live eye textures for the 3D model. The glb shares ONE "EyeScreen" material between EyeL and
// EyeR (EyeR's UVs are mirrored). At runtime each eye gets its own copy of that material and
// its own canvas, so horizontal gaze can be flipped for EyeR and both eyes look the same way.
import { CanvasTexture, MeshStandardMaterial, SRGBColorSpace } from 'three';
import { drawEye } from './drawEyes';
import { mirrorForRightEye, type EyeFrame } from './eyeFrame';

export const EYE_TEXTURE_SIZE = 512;

class EyeCanvas {
  readonly texture: CanvasTexture;
  readonly material: MeshStandardMaterial;
  private readonly ctx: CanvasRenderingContext2D;

  constructor(name: string) {
    const canvas = document.createElement('canvas');
    canvas.width = EYE_TEXTURE_SIZE;
    canvas.height = EYE_TEXTURE_SIZE;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2D canvas is not available for the eye texture');
    this.ctx = ctx;

    this.texture = new CanvasTexture(canvas);
    this.texture.colorSpace = SRGBColorSpace;
    this.texture.flipY = false; // glTF UV convention: v = 0 is the top of the image
    this.texture.anisotropy = 4;

    this.material = new MeshStandardMaterial({
      name,
      color: 0x000000, // the eye is pure light: everything comes from the emissive map
      map: this.texture,
      emissive: 0xffffff,
      emissiveMap: this.texture,
      emissiveIntensity: 1.25,
      roughness: 0.15,
      transparent: true,
      depthWrite: false,
      toneMapped: false, // keep the teal saturated under AgX tone mapping
    });
  }

  draw(frame: EyeFrame): void {
    drawEye(this.ctx, frame, EYE_TEXTURE_SIZE);
    this.texture.needsUpdate = true;
  }

  dispose(): void {
    this.texture.dispose();
    this.material.dispose();
  }
}

export class EyeTextures {
  readonly left = new EyeCanvas('EyeScreen (EyeL)');
  readonly right = new EyeCanvas('EyeScreen (EyeR)');

  draw(frame: EyeFrame): void {
    this.left.draw(frame);
    this.right.draw(mirrorForRightEye(frame));
  }

  dispose(): void {
    this.left.dispose();
    this.right.dispose();
  }
}
