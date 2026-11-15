import type { PetBridge } from '../preload/bridge';

declare global {
  interface Window {
    /** Exposed by src/preload/index.ts. Undefined if the preload failed (the pet still runs). */
    readonly pipi: PetBridge | undefined;
  }
}
