// Small HTML overlays on top of the 3D scene: the brain connection state (discreet, bottom
// right), the model label (bottom left), the "click to enable sound" hint and the duel signal
// glow on the wall (amber = wait, green = go; also announced to screen readers). Text is always
// set with textContent, never as HTML.
import type { BrainStatus } from '@pipi/shared/body';
import type { DuelCue } from '../duelCue';

const STATUS_TEXT: Readonly<Record<BrainStatus, string>> = {
  connecting: 'connecting to brain…',
  connected: 'brain connected',
  disconnected: 'brain offline · retrying',
};

/** What a screen reader hears when the duel signal changes. */
export const CUE_TEXT: Readonly<Record<DuelCue, string>> = {
  none: '',
  countdown: 'Get ready…',
  go: 'Go!',
};

function element<T extends HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`missing element ${selector}`);
  return found;
}

export interface Overlay {
  setStatus(status: BrainStatus, url: string): void;
  setModelLabel(text: string): void;
  setSoundBlocked(blocked: boolean): void;
  /** Duel signal on the wall behind the robot. */
  setCue(cue: DuelCue): void;
}

export function createOverlay(): Overlay {
  const status = element<HTMLElement>('#brain-status');
  const statusText = element<HTMLElement>('#brain-status-text');
  const label = element<HTMLElement>('#model-label');
  const sound = element<HTMLElement>('#sound-hint');
  const glow = element<HTMLElement>('#cue-glow');
  const cueStatus = element<HTMLElement>('#cue-status');
  return {
    setStatus(value, url) {
      status.dataset['state'] = value;
      statusText.textContent = STATUS_TEXT[value];
      status.title = url;
    },
    setModelLabel(text) {
      label.textContent = text;
    },
    setSoundBlocked(blocked) {
      sound.hidden = !blocked;
    },
    setCue(cue) {
      glow.dataset['cue'] = cue;
      cueStatus.textContent = CUE_TEXT[cue];
    },
  };
}
