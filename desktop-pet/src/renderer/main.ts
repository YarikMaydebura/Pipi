// Renderer entry: start the 3D pet, or the 2D fallback if 3D is not possible, then connect to
// the brain. The pet must never be blank: any WebGL/model failure (now or later) switches to
// the fallback; without a brain it keeps living on its own and keeps trying to connect.
// Clicks, drags, hovering and idle time become reactions (interaction/); every click on Pipi
// is also reported to the brain as `user_click` (the study log needs it).
import {
  applyUrlParams,
  calmRequested,
  forceFallbackRequested,
  installDebugKeys,
  isDebugEnabled,
} from './debug/debugKeys';
import { createFallbackView } from './fallback/CssPetView';
import { wirePointerInput } from './input/pointerInput';
import { InteractionController } from './interaction/interactionController';
import {
  BrainClient,
  WebAudioPlayer,
  createSpeechBubble,
  SpeechController,
} from '@pipi/shared/body';
import { createStageMotion } from './migration/stageMotion';
import { Migrator } from './migration/migrator';
import { PetController } from './pet/PetController';
import type { PetView } from './pet/PetView';
import { Showcase, showcaseRequested } from './showcase/showcase';
import { createShowcaseActor } from './showcase/showcaseActor';
import { createShowcaseLabel } from './showcase/showcaseLabel';

const START_TIMEOUT_MS = 8000;
const PET_VERSION = '0.4.0'; // sent in `hello`; bump when the pet's behaviour changes
const CLICK_TARGET = 'pipi'; // `user_click.target` for a click on Pipi itself
const FALLBACK_BRAIN_URL = 'ws://127.0.0.1:8765'; // when the preload bridge is missing

function element<T extends HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`missing element ${selector}`);
  return found;
}

function withTimeout<T>(promise: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(
      () => reject(new Error(`${what} timed out after ${ms} ms`)),
      ms,
    );
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        window.clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

async function boot(): Promise<void> {
  const canvas = element<HTMLCanvasElement>('#pet-canvas');
  const fallbackRoot = element<HTMLElement>('#pet-fallback');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let controller: PetController | null = null;

  const fallBack = (error: unknown): PetView => {
    console.warn('[pipi] 3D pet unavailable, showing the 2D fallback:', error);
    canvas.hidden = true;
    const view = createFallbackView(fallbackRoot);
    view.setReducedMotion(reducedMotion.matches);
    return view;
  };

  let view: PetView;
  let starting: Promise<PetView> | undefined;
  try {
    if (forceFallbackRequested(window.location.search)) throw new Error('?fallback=1 in the URL');
    // Dynamic import: if three.js itself fails to load, the fallback still works.
    const { create3DView } = await import('./scene/Pet3DView');
    starting = create3DView(canvas, {
      reducedMotion: reducedMotion.matches,
      onFatal: (error) => controller?.replaceView(fallBack(error)),
    });
    view = await withTimeout(starting, START_TIMEOUT_MS, '3D pet start');
  } catch (error: unknown) {
    // If the 3D view only finishes after the timeout, throw it away.
    starting?.then(
      (late) => late.dispose(),
      () => undefined,
    );
    view = fallBack(error);
  }

  const pet = new PetController(view);
  controller = pet;
  // Monotonic clock: a system clock change must not stall or rush the idle timeline.
  const interaction = new InteractionController({ target: pet, now: () => performance.now() });
  interaction.setReducedMotion(reducedMotion.matches);
  interaction.setCalm(calmRequested(window.location.search));
  pet.setCalmHandler((on) => interaction.setCalm(on)); // brain `calm` message (study FOCUS)
  pet.setActivityListener((activity, motion) => interaction.brain(activity, motion));
  reducedMotion.addEventListener('change', (event) => {
    pet.currentView.setReducedMotion(event.matches);
    interaction.setReducedMotion(event.matches);
  });

  // Showcase mode plays every animation by itself: no brain, no idle fidgets in between.
  const showcase = showcaseRequested(window.location.search);
  const client = connectToBrain(pet, () => reducedMotion.matches, !showcase);
  wirePointerInput(() => pet.currentView, window.pipi, {
    onPoke: () => {
      interaction.click();
      if (!client.send({ type: 'user_click', target: CLICK_TARGET })) {
        console.info('[pipi] user_click not sent: no brain connection');
      }
    },
    onDrag: (dragging) => interaction.drag(dragging),
    onHover: (over) => interaction.hover(over),
  });
  if (showcase) startShowcase(pet);
  else interaction.start();

  if (isDebugEnabled(window.location.search, import.meta.env.DEV)) {
    installDebugKeys(pet, document.querySelector<HTMLElement>('#debug-label'), {
      toggleCalm: () => {
        interaction.setCalm(!interaction.calm);
        return interaction.calm;
      },
    });
  }
  applyUrlParams(pet, window.location.search);
}

/** `npm run showcase`: loop through every clip and eye state, with its name under Pipi. */
function startShowcase(pet: PetController): void {
  const show = new Showcase({
    actor: createShowcaseActor(pet, window.pipi),
    onStep: createShowcaseLabel(element<HTMLElement>('#showcase-label')),
    onError: (step, error) => console.warn(`[pipi] showcase step "${step.title}" failed:`, error),
  });
  show.start();
  console.info('[pipi] showcase mode: playing every animation in a loop (no brain)');
}

/**
 * Speech, caption bubble and migration services + the WebSocket link to the brain.
 * `connect: false` (showcase mode) sets up the services but never dials the brain.
 */
function connectToBrain(
  pet: PetController,
  reducedMotion: () => boolean,
  connect = true,
): BrainClient {
  const bridge = window.pipi;
  const caption = createSpeechBubble(element<HTMLElement>('#speech-bubble'));
  let client: BrainClient | null = null;
  const speech = new SpeechController({
    player: new WebAudioPlayer(),
    caption,
    outputs: {
      setLevel: (level) => pet.setSpeechLevel(level),
      setTalking: (on) => pet.setTalking(on),
    },
    onDone: (refId, durationMs) => {
      const sent = client?.send({ type: 'speech_done', ref_id: refId, duration_ms: durationMs });
      if (!sent && connect) console.warn('[pipi] speech_done not sent: no brain connection');
    },
  });
  const migration = new Migrator({
    window: bridge ? { command: (command) => bridge.windowCommand(command) } : null,
    stage: createStageMotion(element<HTMLElement>('.pet'), reducedMotion),
    view: () => pet.currentView,
  });
  pet.setServices({ speech, caption, migration });
  client = new BrainClient({
    url: bridge?.brainUrl ?? FALLBACK_BRAIN_URL,
    body: 'desktop_pet',
    version: PET_VERSION,
    handle: (message) => pet.handle(message),
  });
  if (connect) client.start();
  return client;
}

boot().catch((error: unknown) => {
  console.error('[pipi] the pet failed to start:', error);
});
