import type { BrainToBody } from '@pipi/shared';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { backoffDelay, DEFAULT_BACKOFF } from './backoff';
import { BrainClient, type SocketLike } from './brainClient';

class FakeSocket implements SocketLike {
  readyState = 0;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  readonly sent: Record<string, unknown>[] = [];

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.({});
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  receive(message: unknown): void {
    this.onmessage?.({ data: typeof message === 'string' ? message : JSON.stringify(message) });
  }
}

function setup(handle = vi.fn(async (_m: BrainToBody) => ({ ok: true }))) {
  const sockets: FakeSocket[] = [];
  const client = new BrainClient({
    url: 'ws://127.0.0.1:8765',
    version: '0.2.0',
    handle,
    random: () => 0.5, // no jitter
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  return { client, sockets, handle };
}

const flush = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

describe('backoffDelay', () => {
  it('doubles from 0.5 s up to 5 s, with jitter around it', () => {
    const noJitter = (attempt: number) => backoffDelay(attempt, DEFAULT_BACKOFF, () => 0.5);
    expect([0, 1, 2, 3, 4, 10].map(noJitter)).toEqual([500, 1000, 2000, 4000, 5000, 5000]);
    expect(backoffDelay(0, DEFAULT_BACKOFF, () => 0)).toBe(400);
    expect(backoffDelay(0, DEFAULT_BACKOFF, () => 1)).toBe(600);
  });
});

describe('BrainClient', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('says hello when connected', () => {
    const { client, sockets } = setup();
    client.start();
    sockets[0]?.open();
    expect(client.connected).toBe(true);
    expect(sockets[0]?.sent[0]).toMatchObject({
      type: 'hello',
      body: 'desktop_pet',
      version: '0.2.0',
    });
  });

  it('hands valid messages to the pet and acks them', async () => {
    const { client, sockets, handle } = setup();
    client.start();
    const socket = sockets[0] as FakeSocket;
    socket.open();
    socket.receive({ type: 'eyes', id: 'e1', ts: 1, state: 'happy' });
    await flush();
    expect(handle).toHaveBeenCalledWith({ type: 'eyes', id: 'e1', ts: 1, state: 'happy' });
    expect(socket.sent[1]).toMatchObject({ type: 'ack', ref_id: 'e1', ok: true });
  });

  it('acks failures with the error, also when the handler throws', async () => {
    const handle = vi
      .fn<(m: BrainToBody) => Promise<{ ok: boolean; error?: string }>>()
      .mockResolvedValueOnce({ ok: false, error: 'unknown motion: moonwalk' })
      .mockRejectedValueOnce(new Error('boom'));
    const { client, sockets } = setup(handle);
    client.start();
    const socket = sockets[0] as FakeSocket;
    socket.open();
    socket.receive({ type: 'motion', id: 'm1', ts: 1, name: 'moonwalk' });
    socket.receive({ type: 'motion', id: 'm2', ts: 1, name: 'nod' });
    await flush();
    expect(socket.sent.slice(1)).toMatchObject([
      { type: 'ack', ref_id: 'm1', ok: false, error: 'unknown motion: moonwalk' },
      { type: 'ack', ref_id: 'm2', ok: false, error: 'boom' },
    ]);
  });

  it('rejects invalid messages without calling the pet', async () => {
    const { client, sockets, handle } = setup();
    client.start();
    const socket = sockets[0] as FakeSocket;
    socket.open();
    socket.receive({ type: 'eyes', id: 'bad1', ts: 1, state: 'rainbow' });
    socket.receive('{not json');
    await flush();
    expect(handle).not.toHaveBeenCalled();
    expect(socket.sent.slice(1)).toMatchObject([
      { type: 'ack', ref_id: 'bad1', ok: false, error: 'invalid message' },
    ]);
  });

  it('reconnects with backoff and resets it after a successful connect', () => {
    const { client, sockets } = setup();
    client.start();
    sockets[0]?.close(); // brain not running
    vi.advanceTimersByTime(499);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);
    sockets[1]?.close();
    vi.advanceTimersByTime(1000);
    expect(sockets).toHaveLength(3);
    sockets[2]?.open();
    sockets[2]?.close();
    vi.advanceTimersByTime(500);
    expect(sockets).toHaveLength(4);
  });

  it('stops reconnecting after stop() and drops messages while offline', () => {
    const { client, sockets } = setup();
    client.start();
    expect(client.send({ type: 'speech_done', ref_id: 'x', duration_ms: 1 })).toBe(false);
    client.stop();
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });
});
