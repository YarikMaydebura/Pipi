/** IPC channel names shared by main and preload. The renderer never sees these. */
export const IPC = {
  setInteractive: 'pet:set-interactive', // renderer → main: boolean
  drag: 'pet:drag', // renderer → main: 'start' | 'end'
  cursor: 'pet:cursor', // main → renderer: CursorPoint
  window: 'pet:window', // renderer → main (invoke): WindowCommand → boolean
} as const;

/** Cursor position relative to the pet window's top-left corner, in CSS pixels. */
export interface CursorPoint {
  readonly x: number;
  readonly y: number;
}

export type DragPhase = 'start' | 'end';

export type RobotSideName = 'left' | 'right';

/** Window moves for the migration animation (main validates every command). */
export type WindowCommand =
  | { readonly action: 'place'; readonly side: RobotSideName } // jump to the bottom corner
  | { readonly action: 'slide'; readonly side: RobotSideName; readonly durationMs: number }
  | { readonly action: 'hide' }
  | { readonly action: 'show'; readonly side: RobotSideName } // place at the corner + show
  | { readonly action: 'center'; readonly durationMs: number }; // slide to mid-screen (showcase)

/** What the preload script exposes to the renderer as `window.pipi`. Keep it minimal. */
export interface PetBridge {
  readonly platform: string;
  /** true = the window receives mouse events (cursor is over Pipi); false = click-through. */
  setInteractive(interactive: boolean): void;
  /** Start/stop moving the window with the cursor. */
  drag(phase: DragPhase): void;
  /** Global cursor position (~30 Hz), also while the window is click-through. */
  onCursor(listener: (point: CursorPoint) => void): () => void;
  /** Brain WebSocket URL chosen by main (PIPI_BRAIN_URL or the default), or null if unknown. */
  readonly brainUrl: string | null;
  /** Move / hide / show the window; resolves when done (false = rejected by main). */
  windowCommand(command: WindowCommand): Promise<boolean>;
}
