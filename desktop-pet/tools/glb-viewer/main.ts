// Dev tool: preview pipi.glb (every animation clip, eye and mouth images) on a transparent
// background, outside Electron. Run: `npm run viewer` in desktop-pet/.
// The glb comes from the Blender pipeline in assets/pipi3d/ (export.py).
import {
  ACESFilmicToneMapping,
  AnimationMixer,
  Box3,
  Clock,
  DirectionalLight,
  HemisphereLight,
  LoopOnce,
  LoopRepeat,
  Mesh,
  MeshStandardMaterial,
  PerspectiveCamera,
  Scene,
  SRGBColorSpace,
  TextureLoader,
  Vector3,
  WebGLRenderer,
  type AnimationAction,
  type AnimationClip,
  type Object3D,
  type Texture,
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const LOOPING = new Set([
  'idle',
  'talk',
  'think',
  'sleep',
  'listen',
  'dance',
  'look_around',
  'dangle',
]);
const FADE_S = 0.2;

// Vite reads glob options statically, so they must be written inline in each call.
const glbUrls = import.meta.glob<string>('../../../assets/pipi3d/out/pipi.glb', {
  query: '?url',
  import: 'default',
  eager: true,
});
const eyeUrls = import.meta.glob<string>('../../../assets/pipi3d/out/eyes/*.png', {
  query: '?url',
  import: 'default',
  eager: true,
});
const mouthUrls = import.meta.glob<string>('../../../assets/pipi3d/out/mouth/*.png', {
  query: '?url',
  import: 'default',
  eager: true,
});

function byId<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el as T;
}

const stage = byId<HTMLElement>('stage');
const status = byId<HTMLParagraphElement>('status');

function fileName(path: string): string {
  return (path.split('/').pop() ?? path).replace(/\.png$/, '');
}

function makeButton(label: string, onClick: () => void, extraClass?: string): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label; // never innerHTML
  if (extraClass) button.classList.add(extraClass);
  button.addEventListener('click', onClick);
  return button;
}

function selectIn(container: HTMLElement, active: HTMLButtonElement): void {
  for (const b of container.querySelectorAll('button')) b.setAttribute('aria-pressed', 'false');
  active.setAttribute('aria-pressed', 'true');
}

// --- three.js stage (transparent canvas) ---
const renderer = new WebGLRenderer({ antialias: true, alpha: true, premultipliedAlpha: true });
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.toneMapping = ACESFilmicToneMapping;
renderer.outputColorSpace = SRGBColorSpace;
stage.appendChild(renderer.domElement);

const scene = new Scene();
scene.add(new HemisphereLight(0xffffff, 0x9fb4b0, 1.6));
const key = new DirectionalLight(0xffffff, 2.2);
key.position.set(-1, 1.5, 2);
scene.add(key);
const rim = new DirectionalLight(0xdff7ff, 1.4);
rim.position.set(1, 1.2, -2);
scene.add(rim);

const camera = new PerspectiveCamera(30, 1, 0.01, 100);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

function resize(): void {
  const { clientWidth: w, clientHeight: h } = stage;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(1, h);
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

function frame(object: Object3D): void {
  const box = new Box3().setFromObject(object);
  const size = box.getSize(new Vector3());
  const center = box.getCenter(new Vector3());
  const distance = (size.y * 1.4) / (2 * Math.tan((camera.fov * Math.PI) / 360));
  camera.position.copy(center).add(new Vector3(distance * 0.35, size.y * 0.1, distance));
  camera.near = distance / 100;
  camera.far = distance * 20;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
}

// --- animation ---
let mixer: AnimationMixer | null = null;
let current: AnimationAction | null = null;
const actions = new Map<string, AnimationAction>();
const returnIdle = byId<HTMLInputElement>('return-idle');
const speed = byId<HTMLInputElement>('speed');
const clipButtons = byId<HTMLDivElement>('clips');

function play(name: string): void {
  const next = actions.get(name);
  if (!next || !mixer) return;
  const loops = LOOPING.has(name);
  next.reset();
  next.setLoop(loops ? LoopRepeat : LoopOnce, loops ? Infinity : 1);
  next.clampWhenFinished = !loops;
  next.fadeIn(FADE_S).play();
  if (current && current !== next) current.fadeOut(FADE_S);
  current = next;
  const button = [...clipButtons.querySelectorAll('button')].find((b) => b.textContent === name);
  if (button) selectIn(clipButtons, button);
}

function setupClips(clips: AnimationClip[], root: Object3D): void {
  mixer = new AnimationMixer(root);
  mixer.addEventListener('finished', (event) => {
    const finished = event.action as AnimationAction;
    if (returnIdle.checked && finished === current && finished.getClip().name !== 'jump_out') {
      play('idle');
    }
  });
  for (const clip of clips) {
    actions.set(clip.name, mixer.clipAction(clip));
    const extra = LOOPING.has(clip.name) ? 'loop' : undefined;
    clipButtons.appendChild(makeButton(clip.name, () => play(clip.name), extra));
  }
  speed.addEventListener('input', () => {
    if (mixer) mixer.timeScale = Number(speed.value);
  });
}

// --- swappable eye / mouth images ---
const textureLoader = new TextureLoader();

function findMaterial(root: Object3D, name: string): MeshStandardMaterial | null {
  let found: MeshStandardMaterial | null = null;
  root.traverse((obj) => {
    if (found || !(obj instanceof Mesh)) return;
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const mat of mats) {
      if (mat instanceof MeshStandardMaterial && mat.name === name) found = mat;
    }
  });
  return found;
}

function applyImage(material: MeshStandardMaterial, url: string): void {
  textureLoader.load(url, (texture: Texture) => {
    texture.flipY = false; // glTF UV convention
    texture.colorSpace = SRGBColorSpace;
    material.map = texture;
    material.emissiveMap = texture;
    material.needsUpdate = true;
  });
}

function setupImageButtons(
  root: Object3D,
  containerId: string,
  materialName: string,
  urls: Record<string, string>,
): void {
  const container = byId<HTMLDivElement>(containerId);
  const material = findMaterial(root, materialName);
  if (!material) {
    container.textContent = `no ${materialName} material in the glb`;
    return;
  }
  for (const [path, url] of Object.entries(urls)) {
    const button = makeButton(fileName(path), () => {
      applyImage(material, url);
      selectIn(container, button);
    });
    container.appendChild(button);
  }
}

function setupBackgrounds(): void {
  const container = byId<HTMLDivElement>('backgrounds');
  for (const mode of ['checker', 'dark', 'light']) {
    const button = makeButton(mode, () => {
      stage.className = mode;
      selectIn(container, button);
    });
    container.appendChild(button);
  }
}

// --- load ---
const glbUrl = Object.values(glbUrls)[0];
setupBackgrounds();
if (!glbUrl) {
  status.textContent =
    'No pipi.glb yet. Run the Blender pipeline in assets/pipi3d/ (build_pipi → rig → animate → export).';
} else {
  new GLTFLoader().load(
    glbUrl,
    (gltf) => {
      scene.add(gltf.scene);
      frame(gltf.scene);
      setupClips(gltf.animations, gltf.scene);
      setupImageButtons(gltf.scene, 'eyes', 'EyeScreen', eyeUrls);
      setupImageButtons(gltf.scene, 'mouths', 'MouthScreen', mouthUrls);
      status.textContent = `${gltf.animations.length} clips · drag to orbit, scroll to zoom`;
      play('idle');
    },
    undefined,
    (error) => {
      status.textContent = `Could not load pipi.glb: ${String(error)}`;
      console.error(error);
    },
  );
}

const clock = new Clock();
renderer.setAnimationLoop(() => {
  mixer?.update(clock.getDelta());
  controls.update();
  renderer.render(scene, camera);
});
