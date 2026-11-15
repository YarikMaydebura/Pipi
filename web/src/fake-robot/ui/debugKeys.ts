// ?debug=1: try the robot without a brain. w wake up, s sleep, 1–9 0 - = eye states (protocol
// order), n nod, h shake head, v signature wave, a happy, c celebrate, d dance, k think,
// t say a caption-only test line. Messages go through the same controller as the brain's.
import { BrainToBody, EyeState, type WithoutEnvelope } from '@pipi/shared';

const EYE_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='];
const MOTION_KEYS: Readonly<Record<string, string>> = {
  n: 'nod',
  h: 'shake_head',
  v: 'signature_wave',
  a: 'happy',
  c: 'celebrate',
  d: 'dance',
  k: 'think',
};

/** The message a debug key stands for, or null. Pure (unit-tested). */
export function debugMessage(key: string): WithoutEnvelope<BrainToBody> | null {
  if (key === 'w') return { type: 'activate', entrance: 'wake_up' };
  if (key === 's') return { type: 'deactivate', exit: 'sleep' };
  if (key === 't') {
    return { type: 'speak', text: 'Ta-da! Hi again! It is me, Pipi.', expression: 'happy' };
  }
  const motion = MOTION_KEYS[key];
  if (motion) return { type: 'motion', name: motion };
  const eye = EyeState.options[EYE_KEYS.indexOf(key)];
  return eye ? { type: 'eyes', state: eye } : null;
}

let counter = 0;

export function installDebugKeys(handle: (message: BrainToBody) => Promise<unknown>): void {
  window.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const payload = debugMessage(event.key);
    if (!payload) return;
    counter += 1;
    void handle(BrainToBody.parse({ ...payload, id: `debug-${counter}`, ts: Date.now() }));
  });
  console.info('[fake robot] debug keys on: w/s wake/sleep, 1-0 - = eyes, n h v a c d k, t');
}
