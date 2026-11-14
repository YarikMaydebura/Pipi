// Renderer entry. M0 only proves that the shared protocol package works inside Electron.
import { makeBodyMessage, PROTOCOL_VERSION } from '@pipi/shared';

const hello = makeBodyMessage({ type: 'hello', body: 'desktop_pet', version: PROTOCOL_VERSION });

const status = document.querySelector<HTMLParagraphElement>('#status');
if (status) {
  status.textContent = `protocol ${PROTOCOL_VERSION} · ${hello.type} ready · ${window.pipi.platform}`;
}
