// Loads Pipi's 3D model. Candidates, first match wins:
//   1. desktop-pet/src/renderer/assets/pipi.glb   (a copy placed next to the pet's code)
//   2. assets/pipi3d/out/pipi.glb                 (output of the headless Blender scripts)
// otherwise (or if loading fails) the procedural placeholder. The globs are resolved by Vite at
// build time, so a missing file is simply an empty map — no runtime 404.
import type { AnimationClip, Object3D } from 'three';
import { dataUrlToArrayBuffer } from './dataUrl';
import { createPlaceholderRobot } from './placeholderRobot';

export type ModelSource = 'glb' | 'placeholder';

export interface LoadedRobot {
  readonly model: Object3D;
  readonly clips: readonly AnimationClip[];
  readonly source: ModelSource;
}

const GLB_MODULES = import.meta.glob<string>(
  ['../assets/pipi.glb', '../../../../assets/pipi3d/out/pipi.glb'],
  { query: '?inline', import: 'default' },
);

/** The copy next to the pet's code wins over the Blender output folder. */
function pickGlb(): (() => Promise<string>) | undefined {
  const keys = Object.keys(GLB_MODULES).sort(
    (a, b) => Number(a.includes('pipi3d')) - Number(b.includes('pipi3d')),
  );
  return keys[0] === undefined ? undefined : GLB_MODULES[keys[0]];
}

async function loadGlb(importer: () => Promise<string>): Promise<LoadedRobot> {
  const [dataUrl, { GLTFLoader }] = await Promise.all([
    importer(),
    import('three/addons/loaders/GLTFLoader.js'),
  ]);
  const gltf = await new GLTFLoader().parseAsync(dataUrlToArrayBuffer(dataUrl), '');
  return { model: gltf.scene, clips: gltf.animations, source: 'glb' };
}

export async function loadRobot(): Promise<LoadedRobot> {
  const importer = pickGlb();
  if (importer) {
    try {
      return await loadGlb(importer);
    } catch (error: unknown) {
      console.warn('[pipi] pipi.glb failed to load; using the placeholder robot', error);
    }
  }
  return { model: createPlaceholderRobot(), clips: [], source: 'placeholder' };
}
