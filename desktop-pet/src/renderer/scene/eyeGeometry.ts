// Eye quad with the glb UV contract: each eye maps the FULL 0–1 square of the eye image,
// glTF V convention (v = 0 is the top of the image), and EyeR is mirrored horizontally.
import { PlaneGeometry } from 'three';

export function eyeGeometry(size: number, mirrored: boolean): PlaneGeometry {
  const geometry = new PlaneGeometry(size, size, 10, 10);
  const uv = geometry.getAttribute('uv');
  for (let i = 0; i < uv.count; i += 1) {
    const u = uv.getX(i);
    uv.setXY(i, mirrored ? 1 - u : u, 1 - uv.getY(i));
  }
  uv.needsUpdate = true;
  return geometry;
}
