// Runs in an isolated, sandboxed context before the renderer page loads.
// Only the small, explicit PetBridge API is exposed; no Node or ipcRenderer access leaks.
import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';
import { IPC, type CursorPoint, type PetBridge } from './bridge';

// Must match BRAIN_URL_ARG in src/main/brainUrl.ts (the preload is sandboxed: no Node imports).
const BRAIN_URL_ARG = '--pipi-brain-url=';
const brainUrlArg = process.argv.find((arg) => arg.startsWith(BRAIN_URL_ARG));

const bridge: PetBridge = {
  platform: process.platform,
  setInteractive(interactive) {
    ipcRenderer.send(IPC.setInteractive, interactive === true);
  },
  drag(phase) {
    ipcRenderer.send(IPC.drag, phase === 'start' ? 'start' : 'end');
  },
  onCursor(listener) {
    const handler = (_event: IpcRendererEvent, point: CursorPoint): void => listener(point);
    ipcRenderer.on(IPC.cursor, handler);
    return () => {
      ipcRenderer.removeListener(IPC.cursor, handler);
    };
  },
  brainUrl: brainUrlArg ? brainUrlArg.slice(BRAIN_URL_ARG.length) : null,
  async windowCommand(command) {
    const result: unknown = await ipcRenderer.invoke(IPC.window, command);
    return result === true;
  },
};

contextBridge.exposeInMainWorld('pipi', bridge);
