// 2D fallback Pipi (plain HTML/CSS): a dark face screen with teal eyes, a teal mouth and coral
// cheeks. Reaction faces (flashFace) work here too, including the pink "love" eyes.
// Used when WebGL or the 3D model fails, so the pet is never blank. Looks are in style.css.
import type { EyeState } from '@pipi/shared';
import { clamp, type EyeLook } from '../eyes/eyeFrame';
import { lookAt, type ScreenPoint } from '../motion/idle';
import { isKnownMotion, isLoopMotion } from '../motion/motions';
import { computeMouthFrame, mouthForState } from '../mouth/mouthFrame';
import type { MouthShape } from '../mouth/mouthShapes';
import type { PetView } from '../pet/PetView';
import { createFallbackMouth } from './fallbackMouth';

const GAZE_PX = 10;

export function createFallbackView(root: HTMLElement): PetView {
  const face = root.querySelector<HTMLElement>('.fallback-face');
  if (!face) throw new Error('fallback markup is missing (.fallback-face)');
  root.hidden = false;

  const mouth = createFallbackMouth(face);
  let eyeState: EyeState = 'idle';
  let shownState: EyeLook = 'idle';
  let mouthOverride: MouthShape | null = null;
  let flashMouth: MouthShape | null = null;
  let speechLevel = 0;
  let flashTimer: number | undefined;

  const updateMouth = (): void => {
    const shape = mouthOverride ?? flashMouth ?? mouthForState(shownState);
    mouth.show(computeMouthFrame(shownState === 'off' ? 'off' : shape, speechLevel));
  };

  const endFlash = (): void => {
    window.clearTimeout(flashTimer);
    flashMouth = null;
    face.classList.remove('cheeks-flash');
    showState(eyeState);
  };

  const showState = (state: EyeLook): void => {
    shownState = state;
    face.dataset['state'] = state;
    updateMouth();
  };

  const restartAnimation = (name: string): void => {
    face.dataset['motion'] = '';
    void face.offsetWidth; // restart the CSS animation even for the same motion twice
    face.dataset['motion'] = name;
  };

  const view: PetView = {
    kind: 'fallback',
    setEyeState(state) {
      if (state === 'blink') {
        restartAnimation('blink');
        return;
      }
      eyeState = state;
      window.clearTimeout(flashTimer);
      flashMouth = null;
      showState(state);
    },
    playMotion(name) {
      if (name !== 'idle' && !isKnownMotion(name)) return false;
      restartAnimation(name === 'idle' ? '' : 'bounce');
      return true;
    },
    setBaseMotion(name) {
      // The 2D face has no body loops; it only accepts the same names as the 3D pet.
      return name === 'idle' || isLoopMotion(name);
    },
    flashFace(flash) {
      if (!flash) {
        endFlash();
        return;
      }
      window.clearTimeout(flashTimer);
      flashMouth = flash.mouth ?? null;
      face.classList.toggle('cheeks-flash', flash.cheeks === true);
      showState(flash.eyes ?? shownState);
      flashTimer = window.setTimeout(endFlash, flash.durationMs);
    },
    setCursor(point) {
      const box = face.getBoundingClientRect();
      const look = lookAt(point, { x: box.left + box.width / 2, y: box.top + box.height / 2 });
      face.style.setProperty('--gaze-x', `${clamp(look.gazeX, -1, 1) * GAZE_PX}px`);
      face.style.setProperty('--gaze-y', `${clamp(look.gazeY, -1, 1) * GAZE_PX * 0.6}px`);
    },
    hitTest(point: ScreenPoint) {
      const box = face.getBoundingClientRect();
      return (
        point.x >= box.left && point.x <= box.right && point.y >= box.top && point.y <= box.bottom
      );
    },
    setMouthOverride(shape) {
      mouthOverride = shape;
      updateMouth();
    },
    setCheeks(on) {
      face.classList.toggle('cheeks-on', on);
    },
    setChestPulse() {
      // The 2D face has no chest light.
    },
    setSpeechLevel(level) {
      speechLevel = clamp(level, 0, 1);
      face.style.setProperty('--speech-level', speechLevel.toFixed(3));
      updateMouth();
    },
    setReducedMotion(reduced) {
      root.classList.toggle('reduced-motion', reduced);
    },
    dispose() {
      window.clearTimeout(flashTimer);
      root.hidden = true;
    },
  };
  showState(eyeState);
  return view;
}
