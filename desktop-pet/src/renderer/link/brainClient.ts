// WebSocket client to the brain. On every connect it sends `hello`; every message from the brain
// is validated with parseBrainMessage, handed to `handle`, and answered with an `ack`
// (ok or the error). If the brain is not running or goes away, it keeps reconnecting with
// backoff — the pet keeps living on its own meanwhile.
import {
  makeBodyMessage,
  parseBrainMessage,
  type BodyToBrain,
  type BrainToBody,
  type WithoutEnvelope,
} from '@pipi/shared';
import type { HandleResult } from '../pet/PetController';
import { backoffDelay, DEFAULT_BACKOFF, type BackoffOptions } from './backoff';

/** The part of the browser WebSocket the client uses (a fake implements it in tests). */
export interface SocketLike {
  readonly readyState: number;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  send(data: string): void;
  close(): void;
}

const OPEN = 1; // WebSocket.OPEN

export type BrainStatus = 'connecting' | 'connected' | 'disconnected';

export interface BrainClientOptions {
  readonly url: string;
  readonly version: string;
  readonly handle: (message: BrainToBody) => Promise<HandleResult>;
  readonly createSocket?: (url: string) => SocketLike;
  readonly backoff?: BackoffOptions;
  readonly random?: () => number;
  readonly onStatus?: (status: BrainStatus) => void;
}

/** The id of a frame that failed validation, so it can still be acked with an error. */
function extractId(raw: string): string | null {
  try {
    const data: unknown = JSON.parse(raw);
    if (typeof data === 'object' && data !== null) {
      const id = (data as { id?: unknown }).id;
      if (typeof id === 'string' && id.length > 0) return id;
    }
  } catch {
    // not JSON: nothing to ack
  }
  return null;
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export class BrainClient {
  private socket: SocketLike | null = null;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private stopped = true;
  private readonly createSocket: (url: string) => SocketLike;

  constructor(private readonly options: BrainClientOptions) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as SocketLike);
  }

  get connected(): boolean {
    return this.socket?.readyState === OPEN;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.retryTimer);
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  /** Send a body → brain message; false if not connected (the message is dropped). */
  send(payload: WithoutEnvelope<BodyToBrain>): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== OPEN) return false;
    socket.send(JSON.stringify(makeBodyMessage(payload)));
    return true;
  }

  private connect(): void {
    this.options.onStatus?.('connecting');
    let socket: SocketLike;
    try {
      socket = this.createSocket(this.options.url);
    } catch (error: unknown) {
      console.warn('[pipi] cannot open the brain connection:', describe(error));
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.send({ type: 'hello', body: 'desktop_pet', version: this.options.version });
      console.info(`[pipi] connected to the brain at ${this.options.url}`);
      this.options.onStatus?.('connected');
    };
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') void this.onFrame(event.data);
    };
    socket.onerror = () => undefined; // onclose follows and handles the reconnect
    socket.onclose = () => {
      if (this.socket !== socket) return; // an old socket closing after a reconnect
      this.socket = null;
      this.options.onStatus?.('disconnected');
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = backoffDelay(
      this.attempt,
      this.options.backoff ?? DEFAULT_BACKOFF,
      this.options.random,
    );
    this.attempt += 1;
    clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private async onFrame(raw: string): Promise<void> {
    const parsed = parseBrainMessage(raw);
    if (!parsed.ok) {
      console.warn('[pipi] invalid message from the brain:', parsed.error);
      const id = extractId(raw);
      if (id) this.send({ type: 'ack', ref_id: id, ok: false, error: 'invalid message' });
      return;
    }
    let result: HandleResult;
    try {
      result = await this.options.handle(parsed.message);
    } catch (error: unknown) {
      result = { ok: false, error: describe(error) };
    }
    this.send({
      type: 'ack',
      ref_id: parsed.message.id,
      ok: result.ok,
      ...(result.error ? { error: result.error } : {}),
    });
  }
}
