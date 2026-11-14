// Electron main process: creates Pipi's window.
// M0: a normal window. M2 makes it transparent, frameless, always-on-top and click-through.
import { app, BrowserWindow } from 'electron';
import { join } from 'node:path';

const WINDOW_SIZE = { width: 420, height: 320 } as const;
const PRELOAD_PATH = join(import.meta.dirname, '../preload/index.cjs');
const RENDERER_HTML = join(import.meta.dirname, '../renderer/index.html');

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    ...WINDOW_SIZE,
    title: 'Pipi',
    show: false,
    webPreferences: {
      preload: PRELOAD_PATH,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once('ready-to-show', () => win.show());
  // The pet never opens other windows or navigates away from its own page.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event) => event.preventDefault());

  const devServerUrl = process.env['ELECTRON_RENDERER_URL'];
  const load =
    !app.isPackaged && devServerUrl ? win.loadURL(devServerUrl) : win.loadFile(RENDERER_HTML);
  load.catch((error: unknown) => {
    console.error('Failed to load the pet page:', error);
  });

  return win;
}

app
  .whenReady()
  .then(() => {
    createWindow();
    // macOS: re-create the window when the dock icon is clicked and none is open.
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  })
  .catch((error: unknown) => {
    console.error('Electron failed to start:', error);
    app.quit();
  });

// The pet is a single-window app: closing it quits on every OS (including macOS).
app.on('window-all-closed', () => app.quit());
