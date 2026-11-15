// WoZ panel entry: wires the connection, the state reducer, the controls and the view.
// Open it as http://<brain-laptop-ip>:8766/woz/?token=<WOZ_TOKEN> (or `npm run dev` -> /woz/).
import './woz.css';
import { makeWozCommand, type WozCommand } from '@pipi/shared';
import { emergencyPayload, type CommandPayload } from './commands';
import { createComposer } from './composer';
import { WozConnection, tokenFromSearch, wozSocketUrl } from './connection';
import { byId } from './dom';
import { ensureRandomUUID } from './uuid';
import { initialState, reduce, type PanelEvent, type PanelState } from './state';
import { renderAll, renderStatus } from './view';

const TICK_MS = 250;

ensureRandomUUID(); // makeWozCommand needs crypto.randomUUID, missing over plain http on the LAN

let state: PanelState = initialState;
const tokenMissing = tokenFromSearch(location.search) === null;

const connection = new WozConnection(wozSocketUrl(location), dispatch, () => state.failedAttempts);

const composer = createComposer({ send: sendPayload });

function dispatch(event: PanelEvent): void {
  state = reduce(state, event);
  composer.setEnabled(state.connection === 'open');
  byId<HTMLButtonElement>('estop').disabled = state.connection !== 'open';
  renderAll(state, Date.now(), tokenMissing);
}

function sendPayload(payload: CommandPayload): string | null {
  let command: WozCommand;
  try {
    command = makeWozCommand({ ...payload });
  } catch (error: unknown) {
    console.error('invalid WoZ command', error);
    return 'This command could not be built (see the browser console).';
  }
  if (!connection.send(command)) {
    dispatch({
      type: 'command_not_sent',
      command,
      error: 'not connected: nothing was sent',
      at: Date.now(),
    });
    return 'Not connected: nothing was sent.';
  }
  dispatch({ type: 'command_sent', command, at: Date.now() });
  return null;
}

byId('estop').addEventListener('click', () => {
  const draft = composer.draftReason();
  const failure = sendPayload(emergencyPayload(draft.reason, draft.note));
  if (failure) console.error(`emergency stop not sent: ${failure}`);
});

byId('retry').addEventListener('click', () => connection.retryNow());

// Timer and reconnect countdown tick locally between brain updates.
setInterval(() => renderStatus(state, Date.now(), tokenMissing), TICK_MS);

renderAll(state, Date.now(), tokenMissing);
connection.start();
