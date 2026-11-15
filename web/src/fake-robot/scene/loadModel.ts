// Loads alpha_mini.glb (web/public/models/, served at <site>/models/alpha_mini.glb). If it is
// missing, broken or too slow, the primitive stand-in is used instead — the page never stays
// empty. The URL is relative to the page, so it works under the Vite dev server and when the
// brain serves the built web/dist folder.
import type { AnimationClip, Object3D } from 'three';
import { createStandInRobot } from './standIn';

export type ModelSource = 'glb' | 'stand-in';

export interface LoadedModel {
  readonly model: Object3D;
  readonly clips: readonly AnimationClip[];
  readonly source: ModelSource;
}

export const MODEL_PATH = '../models/alpha_mini.glb';
const LOAD_TIMEOUT_MS = 8000;

async function fetchGlb(url: URL): Promise<ArrayBuffer> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LOAD_TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status} for ${url.pathname}`);
    return await response.arrayBuffer();
  } finally {
    clearTimeout(timer);
  }
}

export async function loadModel(pageUrl: string): Promise<LoadedModel> {
  const url = new URL(MODEL_PATH, pageUrl);
  try {
    const [data, { GLTFLoader }] = await Promise.all([
      fetchGlb(url),
      import('three/addons/loaders/GLTFLoader.js'),
    ]);
    const gltf = await new GLTFLoader().parseAsync(data, '');
    return { model: gltf.scene, clips: gltf.animations, source: 'glb' };
  } catch (error: unknown) {
    console.warn('[fake robot] alpha_mini.glb could not be loaded; using the stand-in', error);
    return { model: createStandInRobot(), clips: [], source: 'stand-in' };
  }
}
