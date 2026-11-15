// Main-process side of the pet bridge: click-through toggling, dragging, and a cursor feed.
// The window ignores the mouse while click-through, so the renderer cannot see the cursor
// outside Pipi; main polls the global cursor position and sends it over.
import { ipcMain, screen, type BrowserWindow, type IpcMainEvent } from 'electron';
import { IPC, type CursorPoint } from '../preload/bridge';

const CURSOR_INTERVAL_MS = 33; // ~30 Hz
const DRAG_INTERVAL_MS = 16; // ~60 Hz while dragging, so the window follows smoothly

export function setupPetIpc(win: BrowserWindow): () => void {
  let interactive = false;
  let dragTimer: NodeJS.Timeout | undefined;
  let lastCursor: CursorPoint | null = null;

  /** Only accept messages from Pipi's own page. */
  const fromPet = (event: IpcMainEvent): boolean =>
    !win.isDestroyed() && event.sender === win.webContents;

  const onSetInteractive = (event: IpcMainEvent, value: unknown): void => {
    if (!fromPet(event) || typeof value !== 'boolean' || value === interactive) return;
    interactive = value;
    if (value) win.setIgnoreMouseEvents(false);
    else win.setIgnoreMouseEvents(true, { forward: true });
  };

  const stopDrag = (): void => {
    clearInterval(dragTimer);
    dragTimer = undefined;
  };

  const onDrag = (event: IpcMainEvent, phase: unknown): void => {
    if (!fromPet(event)) return;
    stopDrag();
    if (phase !== 'start') return;
    const start = screen.getCursorScreenPoint();
    const [winX = 0, winY = 0] = win.getPosition();
    const offset = { x: start.x - winX, y: start.y - winY };
    dragTimer = setInterval(() => {
      if (win.isDestroyed()) return stopDrag();
      const point = screen.getCursorScreenPoint();
      win.setPosition(Math.round(point.x - offset.x), Math.round(point.y - offset.y));
    }, DRAG_INTERVAL_MS);
  };

  const cursorTimer = setInterval(() => {
    if (win.isDestroyed() || !win.isVisible()) return;
    const point = screen.getCursorScreenPoint();
    const bounds = win.getBounds();
    const cursor = { x: point.x - bounds.x, y: point.y - bounds.y };
    if (lastCursor && lastCursor.x === cursor.x && lastCursor.y === cursor.y) return;
    lastCursor = cursor;
    win.webContents.send(IPC.cursor, cursor);
  }, CURSOR_INTERVAL_MS);

  ipcMain.on(IPC.setInteractive, onSetInteractive);
  ipcMain.on(IPC.drag, onDrag);
  win.on('blur', stopDrag); // safety: never keep dragging after focus moves elsewhere

  return () => {
    clearInterval(cursorTimer);
    stopDrag();
    ipcMain.removeListener(IPC.setInteractive, onSetInteractive);
    ipcMain.removeListener(IPC.drag, onDrag);
  };
}
