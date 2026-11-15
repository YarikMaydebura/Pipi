// Renderer, camera, lights and environment for a transparent window.
// Soft key / fill / rim lighting plus a neutral studio environment makes plastic read well.
import {
  AgXToneMapping,
  CanvasTexture,
  DirectionalLight,
  HemisphereLight,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  Scene,
  SRGBColorSpace,
  WebGLRenderer,
} from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export const MAX_PIXEL_RATIO = 2;
const CAMERA_FOV = 24;
const CAMERA_POSITION = [0, 0.7, 3.4] as const;
const CAMERA_TARGET_Y = 0.5;

export interface Stage {
  readonly renderer: WebGLRenderer;
  readonly scene: Scene;
  readonly camera: PerspectiveCamera;
  readonly shadow: Mesh;
  resize(): void;
  dispose(): void;
}

function addLights(scene: Scene): void {
  scene.add(new HemisphereLight(0xeaf6ff, 0x3a4048, 0.7));
  const key = new DirectionalLight(0xfff6ea, 2.4);
  key.position.set(1.6, 2.6, 3);
  const fill = new DirectionalLight(0xd8ecff, 0.9);
  fill.position.set(-2.6, 1.2, 2);
  const rimLeft = new DirectionalLight(0xc8fff3, 1.6);
  rimLeft.position.set(-1.5, 2, -2.5);
  const rimRight = new DirectionalLight(0xffffff, 1.2);
  rimRight.position.set(1.8, 1.4, -2.5);
  scene.add(key, fill, rimLeft, rimRight);
}

/** A soft blurred ellipse under the feet so Pipi feels grounded on the desktop. */
function createContactShadow(): Mesh {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const gradient = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    gradient.addColorStop(0, 'rgba(0,0,0,0.45)');
    gradient.addColorStop(0.6, 'rgba(0,0,0,0.15)');
    gradient.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 128, 128);
  }
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  const material = new MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false });
  const shadow = new Mesh(new PlaneGeometry(0.75, 0.42), material);
  shadow.name = 'ContactShadow';
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.002;
  return shadow;
}

/** Throws if WebGL is unavailable; the caller then shows the 2D fallback. */
export function createStage(canvas: HTMLCanvasElement): Stage {
  const renderer = new WebGLRenderer({
    canvas,
    alpha: true,
    premultipliedAlpha: true,
    antialias: true,
    powerPreference: 'low-power',
  });
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = AgXToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.outputColorSpace = SRGBColorSpace;

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  const environment = new RoomEnvironment();
  scene.environment = pmrem.fromScene(environment, 0.04).texture;
  scene.environmentIntensity = 0.55;
  environment.dispose();
  pmrem.dispose();
  addLights(scene);

  const shadow = createContactShadow();
  scene.add(shadow);

  const camera = new PerspectiveCamera(CAMERA_FOV, 1, 0.1, 20);
  camera.position.set(...CAMERA_POSITION);
  camera.lookAt(0, CAMERA_TARGET_Y, 0);

  const resize = (): void => {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  resize();

  return {
    renderer,
    scene,
    camera,
    shadow,
    resize,
    dispose: () => {
      scene.environment?.dispose();
      renderer.dispose();
    },
  };
}
