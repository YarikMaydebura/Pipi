import type { PetBridge } from '../preload/bridge';

declare global {
  interface Window {
    /** Exposed by src/preload/index.ts. */
    readonly pipi: PetBridge;
  }
}
