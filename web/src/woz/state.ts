// Panel state as one immutable value, changed only by reduce() (unit-tested in state.test.ts).
// The DOM is drawn from this state; nothing else holds session data.
import type { BrainToWoz, WozCommand } from '@pipi/shared';

export type StateUpdate = Extract<BrainToWoz, { type: 'state_update' }>;
export type TurnMessage = Extract<BrainToWoz, { type: 'turn' }>;
export type AlertMessage = Extract<BrainToWoz, { type: 'alert' }>;

export type ConnectionStatus = 'connecting' | 'open' | 'closed';

export const TRANSCRIPT_LIMIT = 200;
export const ALERT_LIMIT = 100;
export const COMMAND_LOG_LIMIT = 60;

export interface CommandEntry {
  readonly id: string;
  readonly command: WozCommand['command'];
  readonly args: WozCommand['args'];
  readonly reason: WozCommand['reason'];
  readonly sentAt: number;
  readonly status: 'pending' | 'ok' | 'error';
  readonly error: string | null;
}

export interface AlertEntry {
  readonly id: string;
  readonly at: number;
  readonly level: 'info' | 'warning' | 'error';
  readonly message: string;
  readonly source: 'brain' | 'panel';
}

export interface PanelState {
  readonly connection: ConnectionStatus;
  readonly reconnectAt: number | null; // when the next attempt starts (closed only)
  readonly failedAttempts: number;
  readonly brain: StateUpdate | null;
  readonly stateReceivedAt: number | null; // local clock, for the timer countdown
  readonly transcript: readonly TurnMessage[]; // newest first
  readonly alerts: readonly AlertEntry[]; // newest first
  readonly commands: readonly CommandEntry[]; // newest first
}

export type PanelEvent =
  | { type: 'connecting' }
  | { type: 'opened' }
  | { type: 'closed'; reconnectAt: number }
  | { type: 'message'; message: BrainToWoz; at: number }
  | { type: 'invalid_message'; error: string; at: number }
  | { type: 'command_sent'; command: WozCommand; at: number }
  | { type: 'command_not_sent'; command: WozCommand; error: string; at: number };

export const initialState: PanelState = {
  connection: 'connecting',
  reconnectAt: null,
  failedAttempts: 0,
  brain: null,
  stateReceivedAt: null,
  transcript: [],
  alerts: [],
  commands: [],
};

function prepend<T>(items: readonly T[], item: T, limit: number): readonly T[] {
  return [item, ...items].slice(0, limit);
}

function panelAlert(state: PanelState, message: string, at: number): PanelState {
  const entry: AlertEntry = {
    id: `panel-${at}-${state.alerts.length}`,
    at,
    level: 'error',
    message,
    source: 'panel',
  };
  return { ...state, alerts: prepend(state.alerts, entry, ALERT_LIMIT) };
}

function commandEntry(
  command: WozCommand,
  at: number,
  status: CommandEntry['status'],
  error: string | null,
): CommandEntry {
  return {
    id: command.id,
    command: command.command,
    args: command.args,
    reason: command.reason,
    sentAt: at,
    status,
    error,
  };
}

function applyMessage(state: PanelState, message: BrainToWoz, at: number): PanelState {
  switch (message.type) {
    case 'state_update':
      return { ...state, brain: message, stateReceivedAt: at };
    case 'turn':
      return { ...state, transcript: prepend(state.transcript, message, TRANSCRIPT_LIMIT) };
    case 'alert': {
      const entry: AlertEntry = {
        id: message.id,
        at: message.ts,
        level: message.level,
        message: message.message,
        source: 'brain',
      };
      return { ...state, alerts: prepend(state.alerts, entry, ALERT_LIMIT) };
    }
    case 'ack': {
      const status = message.ok ? 'ok' : 'error';
      const error = message.ok ? null : (message.error ?? 'failed (no reason given)');
      const known = state.commands.some((entry) => entry.id === message.ref_id);
      if (!known) return message.ok ? state : panelAlert(state, `Command rejected: ${error}`, at);
      return {
        ...state,
        commands: state.commands.map((entry) =>
          entry.id === message.ref_id ? { ...entry, status, error } : entry,
        ),
      };
    }
  }
}

export function reduce(state: PanelState, event: PanelEvent): PanelState {
  switch (event.type) {
    case 'connecting':
      return { ...state, connection: 'connecting', reconnectAt: null };
    case 'opened':
      return { ...state, connection: 'open', reconnectAt: null, failedAttempts: 0 };
    case 'closed': {
      // Commands still waiting will never be acked on this connection.
      const commands = state.commands.map((entry) =>
        entry.status === 'pending'
          ? {
              ...entry,
              status: 'error' as const,
              error: 'connection lost before ack: check the brain log',
            }
          : entry,
      );
      return {
        ...state,
        connection: 'closed',
        reconnectAt: event.reconnectAt,
        failedAttempts: state.failedAttempts + 1,
        commands,
      };
    }
    case 'message':
      return applyMessage(state, event.message, event.at);
    case 'invalid_message':
      return panelAlert(state, `Unreadable message from the brain: ${event.error}`, event.at);
    case 'command_sent':
      return {
        ...state,
        commands: prepend(
          state.commands,
          commandEntry(event.command, event.at, 'pending', null),
          COMMAND_LOG_LIMIT,
        ),
      };
    case 'command_not_sent':
      return {
        ...state,
        commands: prepend(
          state.commands,
          commandEntry(event.command, event.at, 'error', event.error),
          COMMAND_LOG_LIMIT,
        ),
      };
  }
}

export type HealthLevel = 'ok' | 'warn' | 'down';

/** Semantic colour for one body: connected and clean = ok, connected with an error = warn. */
export function healthLevel(health: {
  connected: boolean;
  last_error?: string | null;
}): HealthLevel {
  if (!health.connected) return 'down';
  return health.last_error ? 'warn' : 'ok';
}
