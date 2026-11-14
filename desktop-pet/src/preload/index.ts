// Runs in an isolated, sandboxed context before the renderer page loads.
// Only the small, explicit PetBridge API is exposed; no Node access leaks to the page.
import { contextBridge } from 'electron';
import type { PetBridge } from './bridge';

const bridge: PetBridge = {
  platform: process.platform,
};

contextBridge.exposeInMainWorld('pipi', bridge);
