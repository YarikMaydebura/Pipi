// Where the pet finds the brain. Default ws://127.0.0.1:8765 (config/base.yaml server.port);
// override with the PIPI_BRAIN_URL environment variable, e.g. PIPI_BRAIN_URL=ws://127.0.0.1:9000.
// Only loopback addresses are accepted: the brain runs on the same laptop, and the page's CSP
// (connect-src) allows nothing else anyway.

export const DEFAULT_BRAIN_URL = 'ws://127.0.0.1:8765';
const LOOPBACK_WS = /^ws:\/\/(127\.0\.0\.1|localhost):\d{1,5}(\/[\w\-./]*)?$/;

export interface BrainUrlChoice {
  readonly url: string;
  readonly warning?: string;
}

export function resolveBrainUrl(raw: string | undefined): BrainUrlChoice {
  const value = raw?.trim();
  if (!value) return { url: DEFAULT_BRAIN_URL };
  if (LOOPBACK_WS.test(value)) return { url: value };
  return {
    url: DEFAULT_BRAIN_URL,
    warning: `PIPI_BRAIN_URL must look like ws://127.0.0.1:<port>; using ${DEFAULT_BRAIN_URL}`,
  };
}

/** Command-line switch main passes to the (sandboxed) preload via additionalArguments. */
export const BRAIN_URL_ARG = '--pipi-brain-url=';
