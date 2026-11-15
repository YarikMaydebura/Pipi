// Draws the read-only parts of the panel from PanelState (status, timer, lists).
import { describeCommand } from './commands';
import { byId, h, setText } from './dom';
import {
  formatClock,
  formatMs,
  formatTimeOfDay,
  humanize,
  isSlowTurn,
  remainingSeconds,
  timerProgress,
} from './format';
import { healthLevel, type PanelState, type TurnMessage } from './state';

const TIMER_WARN_S = 30;
const HEALTH_LABEL = { ok: 'OK', warn: 'Error', down: 'Offline' } as const;

const el = {
  conn: byId('conn'),
  connText: byId('conn-text'),
  offline: byId('offline'),
  offlineText: byId('offline-text'),
  phase: byId('phase'),
  paused: byId('paused'),
  timer: byId('timer'),
  timerValue: byId('timer-value'),
  timerName: byId('timer-name'),
  timerFill: byId('timer-fill'),
  mode: byId('mode'),
  participant: byId('participant'),
  activeBody: byId('active-body'),
  health: byId('health'),
  alerts: byId('alerts'),
  alertCount: byId('alert-count'),
  transcript: byId('transcript'),
  memory: byId('memory'),
  commandLog: byId('command-log'),
};

export function renderStatus(state: PanelState, now: number, tokenMissing: boolean): void {
  el.conn.dataset.state = state.connection;
  setText(
    el.connText,
    { open: 'Live', connecting: 'Connecting…', closed: 'Disconnected' }[state.connection],
  );
  el.offline.hidden = state.connection === 'open';
  setText(el.offlineText, offlineMessage(state, now, tokenMissing));
  const brain = state.brain;
  setText(el.phase, brain ? brain.phase.replace(/_/g, ' ') : '—');
  el.paused.hidden = !brain?.paused;
  setText(el.mode, brain ? brain.mode.toUpperCase() : '—');
  setText(el.participant, brain?.participant_id ?? '—');
  setText(el.activeBody, brain?.active_body ? humanize(brain.active_body) : 'None');
  renderTimer(state, now);
}

function offlineMessage(state: PanelState, now: number, tokenMissing: boolean): string {
  if (state.connection === 'connecting') return 'Connecting to the brain…';
  const seconds = state.reconnectAt ? Math.max(0, Math.ceil((state.reconnectAt - now) / 1000)) : 0;
  const hint =
    state.failedAttempts >= 3
      ? tokenMissing
        ? ' The page URL has no ?token=… — add the WOZ_TOKEN from .env.'
        : ' Is the brain running? Is the ?token= in the URL right?'
      : '';
  return `No connection to the brain. Commands cannot be sent. Retrying in ${seconds} s.${hint}`;
}

export function renderTimer(state: PanelState, now: number): void {
  const timer = state.brain?.timer;
  el.timer.hidden = !timer;
  if (!timer || state.stateReceivedAt === null) return;
  const remaining = remainingSeconds(
    timer,
    state.stateReceivedAt,
    now,
    state.brain?.paused ?? false,
  );
  setText(el.timerValue, formatClock(remaining));
  setText(el.timerName, `${humanize(timer.name)} · ${formatClock(timer.total_s)}`);
  el.timer.dataset.level = remaining <= 0 ? 'done' : remaining <= TIMER_WARN_S ? 'warn' : 'normal';
  el.timerFill.style.transform = `scaleX(${timerProgress(remaining, timer.total_s)})`;
}

export function renderHealth(state: PanelState): void {
  const entries = Object.entries(state.brain?.health ?? {});
  const items = entries.map(([name, health]) => {
    const level = healthLevel(health);
    return h('li', { className: 'health-item', attrs: { 'data-level': level } }, [
      h('span', { className: 'health-dot', attrs: { 'aria-hidden': 'true' } }),
      h('span', { className: 'health-name', text: humanize(name) }),
      h('span', { className: 'health-state', text: HEALTH_LABEL[level] }),
      health.last_error ? h('span', { className: 'health-error', text: health.last_error }) : null,
    ]);
  });
  el.health.replaceChildren(
    ...(items.length ? items : [h('li', { className: 'empty', text: 'No body reported yet' })]),
  );
}

export function renderAlerts(state: PanelState): void {
  const errors = state.alerts.filter((alert) => alert.level === 'error').length;
  setText(el.alertCount, errors ? String(errors) : '');
  el.alertCount.hidden = errors === 0;
  const items = state.alerts.map((alert) =>
    h('li', { className: 'alert-item', attrs: { 'data-level': alert.level } }, [
      h('time', { className: 'stamp', text: formatTimeOfDay(alert.at) }),
      h('span', {
        className: 'alert-level',
        text: alert.source === 'panel' ? 'panel' : alert.level,
      }),
      h('span', { className: 'alert-text', text: alert.message }),
    ]),
  );
  el.alerts.replaceChildren(
    ...(items.length ? items : [h('li', { className: 'empty', text: 'No alerts' })]),
  );
}

function latencyLine(turn: TurnMessage): HTMLElement | null {
  const lat = turn.latencies;
  if (!lat) return null;
  const parts = [
    ['STT', lat.stt_ms],
    ['LLM', lat.llm_ms],
    ['TTS', lat.tts_ms],
  ] as const;
  return h('p', { className: 'latency' }, [
    ...parts.map(([label, ms]) => h('span', { text: `${label} ${formatMs(ms)}` })),
    h('strong', { text: `total ${formatMs(lat.total_ms)}` }),
  ]);
}

export function renderTranscript(state: PanelState): void {
  const items = state.transcript.map((turn) =>
    h(
      'li',
      {
        className: 'turn',
        attrs: {
          'data-speaker': turn.speaker,
          'data-slow': String(isSlowTurn(turn.latencies?.total_ms)),
        },
      },
      [
        h('div', { className: 'turn-head' }, [
          h('span', {
            className: 'speaker',
            text: turn.speaker === 'pipi' ? 'Pipi' : 'Participant',
          }),
          h('time', { className: 'stamp', text: formatTimeOfDay(turn.ts) }),
        ]),
        h('p', { className: 'turn-text', text: turn.text }),
        latencyLine(turn),
      ],
    ),
  );
  el.transcript.replaceChildren(
    ...(items.length ? items : [h('li', { className: 'empty', text: 'Nothing said yet' })]),
  );
}

export function renderMemory(state: PanelState): void {
  const entries = Object.entries(state.brain?.memory_summary ?? {});
  const rows = entries.flatMap(([key, value]) => [
    h('dt', { text: humanize(key) }),
    h('dd', { text: value }),
  ]);
  el.memory.replaceChildren(
    ...(rows.length ? rows : [h('dd', { className: 'empty', text: 'Empty' })]),
  );
}

export function renderCommandLog(state: PanelState): void {
  const items = state.commands.map((entry) =>
    h('li', { className: 'log-item', attrs: { 'data-status': entry.status } }, [
      h('time', { className: 'stamp', text: formatTimeOfDay(entry.sentAt) }),
      h('span', { className: 'log-command', text: describeCommand(entry.command, entry.args) }),
      h('span', { className: 'log-status', text: entry.status === 'pending' ? '…' : entry.status }),
      h('span', { className: 'log-reason', text: humanize(entry.reason) }),
      entry.error ? h('span', { className: 'log-error', text: entry.error }) : null,
    ]),
  );
  el.commandLog.replaceChildren(
    ...(items.length ? items : [h('li', { className: 'empty', text: 'No commands sent' })]),
  );
}

export function renderAll(state: PanelState, now: number, tokenMissing: boolean): void {
  renderStatus(state, now, tokenMissing);
  renderHealth(state);
  renderAlerts(state);
  renderTranscript(state);
  renderMemory(state);
  renderCommandLog(state);
}
