// Fake robot entry: a browser page that pretends to be the Alpha Mini. It shows the 3D robot on a
// desk (2D fallback if WebGL fails), connects to the brain's body server as `fake_robot` over the
// same protocol as the desktop pet, and carries Pipi's identity cues: teal eyes on the robot's
// displays, Pipi's gpt-4o-mini-tts voice, captions. Settings come from the URL (settings.ts).
import {
  BrainClient,
  createSpeechBubble,
  SpeechController,
  WebAudioPlayer,
} from '@pipi/shared/body';
import { FlatRobotView } from './fallback/FlatRobotView';
import { RobotController } from './robotController';
import type { RobotScene } from './scene/RobotScene';
import { FAKE_ROBOT_VERSION, readSettings } from './settings';
import { SwitchableView, type DisposableView } from './switchableView';
import { installDebugKeys } from './ui/debugKeys';
import { createOverlay } from './ui/overlay';

const START_TIMEOUT_MS = 10000;
const DEBUG_ID_PREFIX = 'debug-';

function element<T extends HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`missing element ${selector}`);
  return found;
}

function timeout(ms: number, what: string): Promise<never> {
  return new Promise((_, reject) =>
    setTimeout(() => reject(new Error(`${what} timed out after ${ms} ms`)), ms),
  );
}

async function createView(
  canvas: HTMLCanvasElement,
  reducedMotion: boolean,
  onFatal: (error: unknown) => void,
): Promise<{ view: DisposableView; label: string }> {
  let starting: Promise<RobotScene> | undefined;
  try {
    // Dynamic import: if three.js itself fails to load, the 2D fallback still works.
    const { createRobotScene } = await import('./scene/RobotScene');
    starting = createRobotScene(canvas, { reducedMotion, onFatal });
    const scene = await Promise.race([starting, timeout(START_TIMEOUT_MS, '3D robot start')]);
    const label =
      scene.source === 'glb' ? 'Alpha Mini (simulated)' : 'Alpha Mini (simulated) · stand-in model';
    return { view: scene, label };
  } catch (error: unknown) {
    starting?.then(
      (late) => late.dispose(),
      () => undefined,
    );
    console.warn('[fake robot] 3D unavailable, showing the 2D face:', error);
    canvas.hidden = true;
    return {
      view: new FlatRobotView(element('#flat-robot')),
      label: 'Alpha Mini (simulated) · 2D',
    };
  }
}

async function boot(): Promise<void> {
  const settings = readSettings(window.location.search, window.location.hostname);
  const overlay = createOverlay();
  const canvas = element<HTMLCanvasElement>('#robot-canvas');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let views: SwitchableView | null = null;
  const fallBack = (error: unknown): void => {
    console.warn('[fake robot] 3D robot failed, switching to the 2D face:', error);
    canvas.hidden = true;
    views?.replace(new FlatRobotView(element('#flat-robot')));
    overlay.setModelLabel('Alpha Mini (simulated) · 2D');
  };
  const { view, label } = await createView(canvas, reducedMotion.matches, fallBack);
  views = new SwitchableView(view);
  overlay.setModelLabel(label);
  reducedMotion.addEventListener('change', (event) => {
    const current = views?.current as Partial<RobotScene> | undefined;
    current?.setReducedMotion?.(event.matches);
  });

  // Autoplay rules: a browser tab may only play audio after a click / key press.
  const player = new WebAudioPlayer();
  overlay.setSoundBlocked(true);
  const unlock = (): void => {
    void player.unlock().then((ok) => overlay.setSoundBlocked(!ok));
  };
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);
  unlock(); // succeeds right away where autoplay is allowed

  let client: BrainClient | null = null;
  let robot: RobotController | null = null;
  const caption = createSpeechBubble(element('#caption'));
  const speech = new SpeechController({
    player,
    caption,
    outputs: {
      setLevel: (level) => robot?.setSpeechLevel(level),
      setTalking: (on) => robot?.setTalking(on),
    },
    onDone: (refId, durationMs) => {
      if (refId.startsWith(DEBUG_ID_PREFIX)) return;
      client?.send({ type: 'speech_done', ref_id: refId, duration_ms: durationMs });
    },
  });
  robot = new RobotController({ view: views, speech, caption, startAwake: settings.startAwake });

  const controller = robot;
  client = new BrainClient({
    url: settings.brainUrl,
    body: 'fake_robot',
    version: FAKE_ROBOT_VERSION,
    handle: (message) => controller.handle(message),
    onStatus: (status) => overlay.setStatus(status, settings.brainUrl),
  });
  client.start();
  if (settings.debug) installDebugKeys((message) => controller.handle(message));
}

void boot().catch((error: unknown) => {
  console.error('[fake robot] could not start:', error);
});
