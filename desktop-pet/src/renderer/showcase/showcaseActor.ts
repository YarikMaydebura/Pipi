// The showcase's hands on the real pet: it uses the same PetController entry points as the
// brain's messages (speak, deactivate, activate), so what is shown is what a session shows.
import type { PetBridge } from '../../preload/bridge';
import type { PetController } from '../pet/PetController';
import type { ShowcaseActor } from './showcase';

const AWAY_MS = 1300; // how long Pipi stays off the screen
const BACK_TO_CENTRE_MS = 900;

let messageIds = 0;
const envelope = (): { id: string; ts: number } => {
  messageIds += 1;
  return { id: `showcase-${messageIds}`, ts: Date.now() };
};

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

export function createShowcaseActor(
  pet: PetController,
  bridge: PetBridge | undefined,
): ShowcaseActor {
  return {
    setEyes: (state) => pet.setEyeState(state),
    playMotion: (name) => {
      const result = pet.playMotion(name);
      if (!result.ok) throw new Error(result.error ?? `unknown motion: ${name}`);
    },
    loveFace: (durationMs) =>
      pet.flashFace({ eyes: 'love', mouth: 'big_smile', cheeks: true, durationMs }),
    say: (text) => {
      void pet.handle({ type: 'speak', text, expression: 'happy', ...envelope() });
    },
    jumpOutAndBack: async () => {
      await pet.handle({ type: 'deactivate', exit: 'jump_out', ...envelope() });
      await wait(AWAY_MS);
      await pet.handle({ type: 'activate', entrance: 'jump_in', ...envelope() });
      if (!bridge) return;
      // Pipi came back in the screen corner: walk it back to the middle for the next round.
      pet.playMotion('happy');
      await bridge.windowCommand({ action: 'center', durationMs: BACK_TO_CENTRE_MS });
    },
  };
}
