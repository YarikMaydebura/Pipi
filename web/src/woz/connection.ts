// The panel's WebSocket to the brain: connect, parse, reconnect with backoff.
import { parseBrainToWozMessage, type WozCommand } from '@pipi/shared';
import { reconnectDelayMs } from './format';
import type { PanelEvent } from './state';

export const WOZ_SOCKET_PATH = '/ws/woz';

export interface PageLocation {
  readonly protocol: string;
  readonly host: string;
  readonly search: string;
}

/** The token from the page URL (?token=...), or null. */
export function tokenFromSearch(search: string): string | null {
  const token = new URLSearchParams(search).get('token');
  return token && token.trim() ? token.trim() : null;
}

/**
 * WebSocket URL on the same host that served the page. In dev, Vite proxies this path to the
 * brain (web/vite.config.ts), so the same code works for `npm run dev` and the built panel.
 */
export function wozSocketUrl(location: PageLocation): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = tokenFromSearch(location.search);
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${scheme}//${location.host}${WOZ_SOCKET_PATH}${query}`;
}

export class WozConnection {
  private socket: WebSocket | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly url: string,
    private readonly dispatch: (event: PanelEvent) => void,
    private readonly failedAttempts: () => number,
  ) {}

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  start(): void {
    this.retryTimer = null;
    this.dispatch({ type: 'connecting' });
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch (error: unknown) {
      console.error('WoZ socket could not be created', error);
      this.scheduleRetry();
      return;
    }
    this.socket = socket;
    socket.addEventListener('open', () => this.dispatch({ type: 'opened' }));
    socket.addEventListener('message', (event: MessageEvent<unknown>) =>
      this.onMessage(event.data),
    );
    socket.addEventListener('close', () => {
      if (this.socket === socket) {
        this.socket = null;
        this.scheduleRetry();
      }
    });
  }

  /** Send a command; false if there is no open connection (nothing was sent). */
  send(command: WozCommand): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(command));
    return true;
  }

  /** Reconnect immediately (the "retry now" button). */
  retryNow(): void {
    if (this.socket) return;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.start();
  }

  private onMessage(data: unknown): void {
    const at = Date.now();
    if (typeof data !== 'string') {
      this.dispatch({ type: 'invalid_message', error: 'binary frame', at });
      return;
    }
    const parsed = parseBrainToWozMessage(data);
    if (parsed.ok) this.dispatch({ type: 'message', message: parsed.message, at });
    else this.dispatch({ type: 'invalid_message', error: parsed.error, at });
  }

  private scheduleRetry(): void {
    const delay = reconnectDelayMs(this.failedAttempts());
    this.dispatch({ type: 'closed', reconnectAt: Date.now() + delay });
    this.retryTimer = setTimeout(() => this.start(), delay);
  }
}
