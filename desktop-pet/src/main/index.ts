// Electron main process: creates Pipi's window and wires the small IPC bridge.
import { app, BrowserWindow } from 'electron';
import { setupPetIpc } from './petIpc';
import { createPetWindow } from './petWindow';
import { setupWindowMover } from './windowMover';

function openPet(): void {
  const win = createPetWindow();
  const teardownIpc = setupPetIpc(win);
  const teardownMover = setupWindowMover(win);
  win.on('closed', () => {
    teardownIpc();
    teardownMover();
  });
}

app
  .whenReady()
  .then(() => {
    openPet();
    // macOS: re-create the window when the dock icon is clicked and none is open.
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) openPet();
    });
  })
  .catch((error: unknown) => {
    console.error('Electron failed to start:', error);
    app.quit();
  });

// The pet is a single-window app: closing it quits on every OS (including macOS).
app.on('window-all-closed', () => app.quit());
