// Creates Pipi's window: transparent, frameless, always on top, click-through except on Pipi.
import { app, BrowserWindow, screen } from 'electron';
import { join } from 'node:path';
import { BRAIN_URL_ARG, resolveBrainUrl } from './brainUrl';
import { cornerPosition } from './windowMath';

export const PET_WINDOW_SIZE = { width: 320, height: 420 } as const;
const PRELOAD_PATH = join(import.meta.dirname, '../preload/index.cjs');
const RENDERER_HTML = join(import.meta.dirname, '../renderer/index.html');

/**
 * Bottom-right corner of the primary display's work area (above the taskbar / dock). Once the
 * brain sends body_config, the renderer moves Pipi to the corner on the robot's side.
 */
function initialPosition(): { x: number; y: number } {
  return cornerPosition(screen.getPrimaryDisplay().workArea, PET_WINDOW_SIZE, 'right');
}

function keepOnTop(win: BrowserWindow): void {
  // 'screen-saver' is the highest level: above normal windows (and the taskbar on Windows).
  win.setAlwaysOnTop(true, 'screen-saver');
  if (process.platform === 'darwin') {
    // macOS only: also show on every Space (desktop) and above full-screen apps.
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }
}

function enableDevTools(win: BrowserWindow): void {
  if (app.isPackaged) return;
  // Dev only: F12 toggles detached DevTools (when Pipi's window has focus — click Pipi first);
  // PIPI_DEVTOOLS=1 opens them at start.
  win.webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.key === 'F12') {
      event.preventDefault();
      win.webContents.toggleDevTools();
    }
  });
  if (process.env['PIPI_DEVTOOLS'] === '1') win.webContents.openDevTools({ mode: 'detach' });
}

export function createPetWindow(): BrowserWindow {
  const brain = resolveBrainUrl(process.env['PIPI_BRAIN_URL']);
  if (brain.warning) console.warn(`[pipi] ${brain.warning}`);
  const win = new BrowserWindow({
    ...PET_WINDOW_SIZE,
    ...initialPosition(),
    title: 'Pipi',
    show: false,
    transparent: true,
    backgroundColor: '#00000000',
    frame: false,
    hasShadow: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    webPreferences: {
      preload: PRELOAD_PATH,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false, // keep animating while another app has focus
      autoplayPolicy: 'no-user-gesture-required', // Pipi speaks without being clicked first
      additionalArguments: [`${BRAIN_URL_ARG}${brain.url}`], // read by the preload
    },
  });

  keepOnTop(win);
  // Start click-through; the renderer turns mouse events on while the cursor is over Pipi.
  // `forward: true` still delivers mouse-move events so the renderer can hit-test.
  win.setIgnoreMouseEvents(true, { forward: true });

  win.once('ready-to-show', () => win.showInactive());
  // The pet never opens other windows or navigates away from its own page.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  enableDevTools(win);

  const devServerUrl = process.env['ELECTRON_RENDERER_URL'];
  const load =
    !app.isPackaged && devServerUrl ? win.loadURL(devServerUrl) : win.loadFile(RENDERER_HTML);
  load.catch((error: unknown) => {
    console.error('Failed to load the pet page:', error);
  });

  return win;
}
