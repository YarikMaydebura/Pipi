// WoZ panel entry. M0 only proves the shared protocol package loads in this page.
import { EyeState, PROTOCOL_VERSION } from '@pipi/shared';
import { showStatus } from '../common/status';

showStatus(`protocol ${PROTOCOL_VERSION} · ${EyeState.options.length} eye states known`);
