// Page settings from the URL. Pure (pass in location parts), so they are unit-tested.
//
//   ?brain=ws://192.168.1.20:8765   brain body server to connect to (default: this page's host)
//   ?awake=1                        start awake (eyes on, idle) instead of asleep
//   ?debug=1                        keyboard shortcuts for trying motions without a brain

/** Sent in `hello`; bump when the fake robot's behaviour changes. */
export const FAKE_ROBOT_VERSION = '0.1.0';
export const DEFAULT_BRAIN_PORT = 8765;

export interface PageSettings {
  readonly brainUrl: string;
  readonly startAwake: boolean;
  readonly debug: boolean;
}

function flag(params: URLSearchParams, name: string): boolean {
  const value = params.get(name);
  return value !== null && value !== '0' && value !== 'false';
}

/** A ws:// or wss:// URL with a host, or null if `raw` is anything else. */
export function validBrainUrl(raw: string): string | null {
  try {
    const url = new URL(raw);
    if ((url.protocol !== 'ws:' && url.protocol !== 'wss:') || !url.hostname) return null;
    return url.toString().replace(/\/$/, '');
  } catch {
    return null;
  }
}

/**
 * Default brain URL: same machine that served the page, port 8765. A page opened from a file
 * (no hostname) talks to 127.0.0.1.
 */
export function defaultBrainUrl(hostname: string): string {
  const host = hostname || '127.0.0.1';
  const bracketed = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host;
  return `ws://${bracketed}:${DEFAULT_BRAIN_PORT}`;
}

export function readSettings(search: string, hostname: string): PageSettings {
  const params = new URLSearchParams(search);
  const requested = params.get('brain');
  const custom = requested ? validBrainUrl(requested) : null;
  if (requested && !custom) {
    console.warn(`[fake robot] ignoring ?brain=${requested}: expected ws://host:port`);
  }
  return {
    brainUrl: custom ?? defaultBrainUrl(hostname),
    startAwake: flag(params, 'awake'),
    debug: flag(params, 'debug'),
  };
}
