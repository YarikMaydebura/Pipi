// Fake robot entry. M0 only proves the shared protocol package loads in this page.
import { makeBodyMessage, PROTOCOL_VERSION } from '@pipi/shared';
import { showStatus } from '../common/status';

const hello = makeBodyMessage({ type: 'hello', body: 'fake_robot', version: PROTOCOL_VERSION });
showStatus(`protocol ${PROTOCOL_VERSION} · ${hello.type} ready`);
