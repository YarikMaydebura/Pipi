// Main-process side of the migration: moves, hides and shows Pipi's window on request of the
// renderer (which plays the matching animation). Commands are validated; only Pipi's own page
// may send them.
import { ipcMain, screen, type BrowserWindow, type IpcMainInvokeEvent } from 'electron';
import { IPC, type RobotSideName } from '../preload/bridge';
import {
  centerPosition,
  cornerPosition,
  easeInOutCubic,
  lerpPoint,
  parseWindowCommand,
  type Point,
} from './windowMath';

const FRAME_MS = 16; // ~60 Hz

export function setupWindowMover(win: BrowserWindow): () => void {
  let timer: NodeJS.Timeout | undefined;
  let finishSlide: (() => void) | undefined;

  const stopSlide = (): void => {
    clearInterval(timer);
    timer = undefined;
    finishSlide?.();
    finishSlide = undefined;
  };

  const corner = (side: RobotSideName): Point => {
    const display = screen.getDisplayMatching(win.getBounds());
    const [width = 0, height = 0] = win.getSize();
    return cornerPosition(display.workArea, { width, height }, side);
  };

  const center = (): Point => {
    const display = screen.getDisplayMatching(win.getBounds());
    const [width = 0, height = 0] = win.getSize();
    return centerPosition(display.workArea, { width, height });
  };

  const slide = (to: Point, durationMs: number): Promise<void> => {
    stopSlide();
    const [x = 0, y = 0] = win.getPosition();
    const from = { x, y };
    if (durationMs <= 0) {
      win.setPosition(to.x, to.y);
      return Promise.resolve();
    }
    const start = Date.now();
    return new Promise<void>((resolve) => {
      finishSlide = resolve;
      timer = setInterval(() => {
        if (win.isDestroyed()) return stopSlide();
        const t = Math.min(1, (Date.now() - start) / durationMs);
        const point = lerpPoint(from, to, easeInOutCubic(t));
        win.setPosition(point.x, point.y);
        if (t >= 1) stopSlide();
      }, FRAME_MS);
    });
  };

  const onCommand = async (event: IpcMainInvokeEvent, raw: unknown): Promise<boolean> => {
    if (win.isDestroyed() || event.sender !== win.webContents) return false;
    const command = parseWindowCommand(raw);
    if (!command) return false;
    switch (command.action) {
      case 'place': {
        stopSlide();
        const point = corner(command.side);
        win.setPosition(point.x, point.y);
        return true;
      }
      case 'slide':
        await slide(corner(command.side), command.durationMs);
        return true;
      case 'center':
        await slide(center(), command.durationMs);
        return true;
      case 'hide':
        stopSlide();
        win.hide();
        return true;
      case 'show': {
        stopSlide();
        const point = corner(command.side);
        win.setPosition(point.x, point.y);
        win.showInactive(); // never steal focus from the participant's reading
        return true;
      }
    }
  };

  ipcMain.handle(IPC.window, onCommand);
  return () => {
    stopSlide();
    ipcMain.removeHandler(IPC.window);
  };
}
