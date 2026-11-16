// Renderer, camera, lights and the desk the robot stands on. Warm "desk lamp" key light with
// soft shadows, a cool rim so the white shell separates from the background on a projector,
// and a neutral studio environment (generated locally, no network) for glossy plastic.
// For the duel there is a signal cue: a coloured light on the robot and a soft glowing ring on
// the desk around its feet (off by default; RobotScene drives it from the eye state).
// The canvas is transparent: the wall behind the desk is a CSS gradient (fake-robot.css).
import {
  ACESFilmicToneMapping,
  AmbientLight,
  BoxGeometry,
  CanvasTexture,
  CylinderGeometry,
  DirectionalLight,
  Group,
  HemisphereLight,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PCFShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  PointLight,
  RepeatWrapping,
  Scene,
  SRGBColorSpace,
  TorusGeometry,
  Vector3,
  WebGLRenderer,
} from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export const MAX_PIXEL_RATIO = 2;
const CAMERA_FOV = 28;
/** Where the camera looks: about the robot's chest (robot height = 1). */
export const CAMERA_TARGET = new Vector3(0, 0.6, 0);
const CAMERA_HOME = new Vector3(0, 0.84, 3.2);
/** Visible width the camera keeps on narrow (portrait) screens, in robot heights. */
const MIN_VISIBLE_WIDTH = 1.5;

export interface Stage {
  readonly renderer: WebGLRenderer;
  readonly scene: Scene;
  readonly camera: PerspectiveCamera;
  /** Slow camera drift (0 = still, e.g. reduced motion); `t` in seconds. */
  drift(t: number, amount: number): void;
  /** Signal cue: tint light + desk ring in `color` (CSS hex), `strength` 0 (off) .. 1. */
  setCue(color: string, strength: number): void;
  resize(): void;
  dispose(): void;
}

function addLights(scene: Scene): void {
  scene.add(new HemisphereLight(0xfff4e6, 0x3b2f28, 0.55));
  scene.add(new AmbientLight(0xffffff, 0.08));

  const key = new DirectionalLight(0xffe8cc, 2.6); // warm desk lamp, upper left
  key.position.set(-1.6, 2.8, 2.2);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -1.2;
  key.shadow.camera.right = 1.2;
  key.shadow.camera.top = 1.6;
  key.shadow.camera.bottom = -0.6;
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 8;
  key.shadow.radius = 6;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;

  const fill = new DirectionalLight(0xdfeeff, 0.8);
  fill.position.set(2.4, 1.4, 2.6);
  const rim = new DirectionalLight(0xbff8ee, 1.8); // teal-ish rim: Pipi's colour in the edge light
  rim.position.set(1.4, 2.2, -2.4);
  const back = new DirectionalLight(0xffffff, 0.9);
  back.position.set(-1.8, 1.6, -2.2);
  scene.add(key, fill, rim, back);
}

const CUE_RING_SIZE = 2.1; // robot heights: the ring's glow reaches a bit past the feet
const CUE_RING_OPACITY = 0.8; // plain (not additive) blending: the colour survives on light wood
const CUE_LIGHT_INTENSITY = 5;

/** A soft ring (transparent centre, glowing band, soft edge) drawn on a canvas. */
function ringTexture(): CanvasTexture {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const glow = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    glow.addColorStop(0, 'rgba(255,255,255,0.22)');
    glow.addColorStop(0.42, 'rgba(255,255,255,0.3)');
    glow.addColorStop(0.6, 'rgba(255,255,255,1)');
    glow.addColorStop(0.72, 'rgba(255,255,255,0.35)');
    glow.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, size, size);
  }
  return new CanvasTexture(canvas);
}

interface CueParts {
  readonly light: PointLight;
  readonly ring: Mesh<PlaneGeometry, MeshBasicMaterial>;
}

/** The duel signal: a coloured light in front of the robot and a ring on the desk (both off). */
function createCue(scene: Scene): CueParts {
  const light = new PointLight(0xffffff, 0, 6, 1.6);
  light.position.set(0, 0.95, 1.5);
  const ring = new Mesh(
    new PlaneGeometry(CUE_RING_SIZE, CUE_RING_SIZE),
    new MeshBasicMaterial({
      map: ringTexture(),
      transparent: true,
      opacity: 0,
      depthWrite: false,
      toneMapped: false,
    }),
  );
  ring.name = 'CueRing';
  ring.rotation.x = -Math.PI / 2;
  ring.position.set(0, 0.004, 0);
  ring.visible = false;
  scene.add(light, ring);
  return { light, ring };
}

/** Oak-like wood grain drawn on a canvas (no image files to load). */
function woodTexture(): CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const base = ctx.createLinearGradient(0, 0, 0, canvas.height);
    base.addColorStop(0, '#b98a5e');
    base.addColorStop(1, '#a87a50');
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < 140; i += 1) {
      const y = (i / 140) * canvas.height;
      const wobble = 6 + (i % 7) * 2;
      ctx.strokeStyle = `rgba(${90 + (i % 5) * 8},${58 + (i % 3) * 6},${34},${0.08 + (i % 4) * 0.03})`;
      ctx.lineWidth = 1 + (i % 3);
      ctx.beginPath();
      for (let x = 0; x <= canvas.width; x += 16) {
        const yy = y + Math.sin(x / (90 + (i % 9) * 14) + i) * wobble;
        if (x === 0) ctx.moveTo(x, yy);
        else ctx.lineTo(x, yy);
      }
      ctx.stroke();
    }
  }
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.repeat.set(2, 1);
  texture.anisotropy = 8;
  return texture;
}

/** The desk plus a few quiet props (notebook, pencil, mug) so the scene reads as a study desk. */
function createDesk(): Group {
  const desk = new Group();
  desk.name = 'Desk';
  const top = new Mesh(
    new BoxGeometry(7, 0.12, 3.2),
    new MeshStandardMaterial({ map: woodTexture(), roughness: 0.55, metalness: 0 }),
  );
  top.position.set(0, -0.06, -0.4);
  top.receiveShadow = true;
  desk.add(top);

  const notebook = new Mesh(
    new BoxGeometry(0.72, 0.035, 0.98),
    new MeshStandardMaterial({ color: 0x2f5d62, roughness: 0.8 }),
  );
  notebook.position.set(-1.05, 0.018, -0.45);
  notebook.rotation.y = 0.32;
  const pages = new Mesh(
    new BoxGeometry(0.68, 0.025, 0.94),
    new MeshStandardMaterial({ color: 0xf4efe4, roughness: 0.9 }),
  );
  pages.position.set(0.02, 0.03, 0);
  notebook.add(pages);
  const pencil = new Mesh(
    new CylinderGeometry(0.012, 0.012, 0.62, 12),
    new MeshStandardMaterial({ color: 0xf2b134, roughness: 0.5 }),
  );
  pencil.rotation.set(0, 0, Math.PI / 2);
  pencil.position.set(0.05, 0.06, 0.25);
  notebook.add(pencil);

  const mugMaterial = new MeshStandardMaterial({ color: 0xff8a7a, roughness: 0.35 }); // coral
  const mug = new Mesh(new CylinderGeometry(0.15, 0.14, 0.34, 40), mugMaterial);
  mug.position.set(1.15, 0.17, -0.7);
  const handle = new Mesh(new TorusGeometry(0.075, 0.022, 12, 28), mugMaterial);
  handle.position.set(0.16, 0, 0);
  handle.rotation.y = 0;
  mug.add(handle);

  for (const prop of [notebook, pages, pencil, mug, handle]) {
    prop.castShadow = true;
    prop.receiveShadow = true;
  }
  desk.add(notebook, mug);
  return desk;
}

/** Throws if WebGL is unavailable; the caller then shows the 2D fallback. */
export function createStage(canvas: HTMLCanvasElement): Stage {
  const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFShadowMap;

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  const environment = new RoomEnvironment();
  scene.environment = pmrem.fromScene(environment, 0.04).texture;
  scene.environmentIntensity = 0.45;
  environment.dispose();
  pmrem.dispose();
  addLights(scene);
  scene.add(createDesk());
  const cue = createCue(scene);

  const camera = new PerspectiveCamera(CAMERA_FOV, 1, 0.1, 30);
  let distanceScale = 1;
  const place = (offsetX: number, offsetY: number): void => {
    const home = CAMERA_HOME.clone().sub(CAMERA_TARGET).multiplyScalar(distanceScale);
    camera.position
      .copy(CAMERA_TARGET)
      .add(home)
      .add(new Vector3(offsetX, offsetY, 0));
    camera.lookAt(CAMERA_TARGET);
  };

  const resize = (): void => {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    // Portrait screens: move back so the robot (and a bit of desk) still fits the width.
    const distance = CAMERA_HOME.distanceTo(CAMERA_TARGET);
    const visibleWidth = 2 * distance * Math.tan((CAMERA_FOV * Math.PI) / 360) * camera.aspect;
    distanceScale = Math.max(1, MIN_VISIBLE_WIDTH / visibleWidth);
    place(0, 0);
  };
  resize();

  return {
    renderer,
    scene,
    camera,
    drift: (t, amount) => {
      if (amount <= 0) return;
      place(0.05 * amount * Math.sin(t * 0.13), 0.025 * amount * Math.sin(t * 0.09 + 1));
    },
    setCue: (color, strength) => {
      const level = Math.min(1, Math.max(0, strength));
      cue.ring.visible = level > 0.002;
      cue.ring.material.opacity = CUE_RING_OPACITY * level;
      cue.light.intensity = CUE_LIGHT_INTENSITY * level;
      if (level > 0) {
        cue.ring.material.color.set(color);
        cue.light.color.set(color);
      }
    },
    resize,
    dispose: () => {
      cue.ring.material.map?.dispose();
      cue.ring.material.dispose();
      cue.ring.geometry.dispose();
      scene.environment?.dispose();
      renderer.dispose();
    },
  };
}
