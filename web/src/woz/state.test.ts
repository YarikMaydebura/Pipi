import { makeWozCommand, type BrainToWoz } from '@pipi/shared';
import { describe, expect, it } from 'vitest';
import {
  COMMAND_LOG_LIMIT,
  TRANSCRIPT_LIMIT,
  healthLevel,
  initialState,
  reduce,
  type PanelState,
} from './state';

const stateUpdate: BrainToWoz = {
  type: 'state_update',
  id: 's1',
  ts: 1,
  phase: 'FOCUS',
  mode: 'study',
  participant_id: 'P01',
  active_body: 'desktop_pet',
  timer: { name: 'focus', remaining_s: 200, total_s: 240 },
  paused: false,
  memory_summary: { name: 'Sam' },
  health: { desktop_pet: { connected: true } },
};

function turn(id: string, text = 'hi'): BrainToWoz {
  return { type: 'turn', id, ts: 2, speaker: 'user', text, latencies: { total_ms: 1200 } };
}

function sent(state: PanelState): { state: PanelState; id: string } {
  const command = makeWozCommand({ command: 'pause', args: {}, reason: 'timing' });
  return { state: reduce(state, { type: 'command_sent', command, at: 10 }), id: command.id };
}

describe('reduce', () => {
  it('does not mutate the previous state', () => {
    const before = initialState;
    const after = reduce(before, { type: 'message', message: stateUpdate, at: 5 });
    expect(before.brain).toBeNull();
    expect(after.brain?.phase).toBe('FOCUS');
    expect(after.stateReceivedAt).toBe(5);
  });

  it('tracks the connection and resets failures when open', () => {
    let state = reduce(initialState, { type: 'closed', reconnectAt: 100 });
    state = reduce(state, { type: 'closed', reconnectAt: 200 });
    expect(state).toMatchObject({ connection: 'closed', failedAttempts: 2, reconnectAt: 200 });
    state = reduce(state, { type: 'opened' });
    expect(state).toMatchObject({ connection: 'open', failedAttempts: 0, reconnectAt: null });
  });

  it('keeps the transcript newest first and bounded', () => {
    let state = initialState;
    for (let i = 0; i < TRANSCRIPT_LIMIT + 5; i += 1) {
      state = reduce(state, { type: 'message', message: turn(`t${i}`), at: i });
    }
    expect(state.transcript).toHaveLength(TRANSCRIPT_LIMIT);
    expect(state.transcript[0]?.id).toBe(`t${TRANSCRIPT_LIMIT + 4}`);
  });

  it('matches acks to sent commands', () => {
    const { state, id } = sent(initialState);
    expect(state.commands[0]?.status).toBe('pending');
    const ok = reduce(state, {
      type: 'message',
      message: { type: 'ack', id: 'a', ts: 1, ref_id: id, ok: true },
      at: 11,
    });
    expect(ok.commands[0]).toMatchObject({ status: 'ok', error: null });
    const failed = reduce(state, {
      type: 'message',
      message: { type: 'ack', id: 'a', ts: 1, ref_id: id, ok: false, error: 'no game running' },
      at: 11,
    });
    expect(failed.commands[0]).toMatchObject({ status: 'error', error: 'no game running' });
  });

  it('turns an error ack for an unknown command into a panel alert', () => {
    const state = reduce(initialState, {
      type: 'message',
      message: {
        type: 'ack',
        id: 'a',
        ts: 1,
        ref_id: 'unknown',
        ok: false,
        error: 'invalid command',
      },
      at: 3,
    });
    expect(state.alerts[0]).toMatchObject({ level: 'error', source: 'panel' });
    expect(state.alerts[0]?.message).toContain('invalid command');
  });

  it('marks pending commands as failed when the connection drops', () => {
    const { state } = sent(initialState);
    const closed = reduce(state, { type: 'closed', reconnectAt: 50 });
    expect(closed.commands[0]?.status).toBe('error');
    expect(closed.commands[0]?.error).toMatch(/connection lost/);
  });

  it('records commands that could not be sent and bounds the log', () => {
    let state = initialState;
    for (let i = 0; i < COMMAND_LOG_LIMIT + 3; i += 1) state = sent(state).state;
    expect(state.commands).toHaveLength(COMMAND_LOG_LIMIT);
    const command = makeWozCommand({ command: 'resume', args: {}, reason: 'timing' });
    state = reduce(state, { type: 'command_not_sent', command, error: 'not connected', at: 1 });
    expect(state.commands[0]).toMatchObject({
      command: 'resume',
      status: 'error',
      error: 'not connected',
    });
  });

  it('adds brain alerts and unreadable messages to the alert list', () => {
    let state = reduce(initialState, {
      type: 'message',
      message: { type: 'alert', id: 'x', ts: 9, level: 'warning', message: 'robot slow' },
      at: 9,
    });
    state = reduce(state, { type: 'invalid_message', error: 'bad json', at: 10 });
    expect(state.alerts.map((alert) => alert.source)).toEqual(['panel', 'brain']);
  });
});

describe('healthLevel', () => {
  it('maps body health to semantic levels', () => {
    expect(healthLevel({ connected: true })).toBe('ok');
    expect(healthLevel({ connected: true, last_error: 'ack timeout' })).toBe('warn');
    expect(healthLevel({ connected: false, last_error: null })).toBe('down');
  });
});
