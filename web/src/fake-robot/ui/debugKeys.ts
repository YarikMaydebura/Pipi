// ?debug=1: try the robot without a brain. Messages go through the same controller as the
// brain's, so what you see is what the brain gets.
//   w wake up     s sleep     t say a caption-only test line     Escape emergency stop
//   1 2 3 4 5 6 7 8 9 0 - =   eye states in protocol order (… - countdown, = signal_go)
//   social:     n nod   h shake_head   v signature_wave   a happy   c celebrate   d dance
//               k think   e sad   i shrug   o bow
//   crocodile:  b act_bird   x act_boxer   m act_swimmer   j act_dancer   r act_robot
//               z act_sleeping   u act_superhero   p act_drummer   (they repeat until the next
//               motion or Escape)
//   duel:       g duel_ready (holds)   f duel_draw   q duel_hit   y duel_win
//               a whole round by hand: g  -  (wait)  =  f
//   staring:    [ stare_ready (holds)   ] stare_lose
//   rps:        , rps_shake   . rps_rock   / rps_paper   ; rps_scissors (the choices hold)
import { BrainToBody, EyeState, type WithoutEnvelope } from '@pipi/shared';

export const EYE_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '='];
export const STOP_KEY = 'Escape';
export const MOTION_KEYS: Readonly<Record<string, string>> = {
  n: 'nod',
  h: 'shake_head',
  v: 'signature_wave',
  a: 'happy',
  c: 'celebrate',
  d: 'dance',
  k: 'think',
  e: 'sad',
  i: 'shrug',
  o: 'bow',
  b: 'act_bird',
  x: 'act_boxer',
  m: 'act_swimmer',
  j: 'act_dancer',
  r: 'act_robot',
  z: 'act_sleeping',
  u: 'act_superhero',
  p: 'act_drummer',
  g: 'duel_ready',
  f: 'duel_draw',
  q: 'duel_hit',
  y: 'duel_win',
  '[': 'stare_ready',
  ']': 'stare_lose',
  ',': 'rps_shake',
  '.': 'rps_rock',
  '/': 'rps_paper',
  ';': 'rps_scissors',
};

/** The message a debug key stands for, or null. Pure (unit-tested). */
export function debugMessage(key: string): WithoutEnvelope<BrainToBody> | null {
  if (key === 'w') return { type: 'activate', entrance: 'wake_up' };
  if (key === 's') return { type: 'deactivate', exit: 'sleep' };
  if (key === STOP_KEY) return { type: 'stop' };
  if (key === 't') {
    return { type: 'speak', text: 'Ta-da! Hi again! It is me, Pipi.', expression: 'happy' };
  }
  const motion = Object.hasOwn(MOTION_KEYS, key) ? MOTION_KEYS[key] : undefined;
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
  console.info(
    '[fake robot] debug keys on: w/s wake/sleep, t test line, Escape stop, 1-0 - = eyes ' +
      '(- countdown, = signal_go); motions: ' +
      Object.entries(MOTION_KEYS)
        .map(([key, name]) => `${key} ${name}`)
        .join(', '),
  );
}
