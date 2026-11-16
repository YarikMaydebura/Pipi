// Page settings from the URL. Pure (pass in location parts), so they are unit-tested.
//
//   ?brain=ws://192.168.1.20:8765   brain body server to connect to (default: this page's host)
//   ?awake=1                        start awake (eyes on, idle) instead of asleep
//   ?debug=1                        keyboard shortcuts for trying motions without a brain
//   ?motion=act_bird                play this motion once the page has started (needs ?awake=1)
//   ?eyes=countdown                 show this eye state at the start (needs ?awake=1)
//   ?gosound=0                      no "go" sound when the eyes turn green (duel)
//   ?clips=0                        ignore the model's animation clips: every motion is the
//                                   procedural fallback (to check the fallbacks by hand)

import { EyeState } from '@pipi/shared';

/** Sent in `hello`; bump when the fake robot's behaviour changes. */
export const FAKE_ROBOT_VERSION = '0.2.0';
export const DEFAULT_BRAIN_PORT = 8765;

export interface PageSettings {
  readonly brainUrl: string;
  readonly startAwake: boolean;
  readonly debug: boolean;
  /** Play the short "go" sound when the eyes switch to signal_go (on unless ?gosound=0). */
  readonly goSound: boolean;
  /** Use the glb's animation clips (off with ?clips=0: procedural fallbacks only). */
  readonly useClips: boolean;
  /** A motion name to play at the start, or null (unknown names are refused like the brain's). */
  readonly startMotion: string | null;
  /** An eye state to show at the start, or null. */
  readonly startEyes: EyeState | null;
}

/** Same rule as the brain's motion names. */
const MOTION_NAME = /^[a-z0-9_]{1,64}$/;

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

function startMotion(raw: string | null): string | null {
  if (raw === null) return null;
  if (MOTION_NAME.test(raw)) return raw;
  console.warn('[fake robot] ignoring ?motion=: expected a name like act_bird');
  return null;
}

function startEyes(raw: string | null): EyeState | null {
  if (raw === null) return null;
  const parsed = EyeState.safeParse(raw);
  if (parsed.success) return parsed.data;
  console.warn('[fake robot] ignoring ?eyes=: not an eye state');
  return null;
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
    goSound: params.get('gosound') === null || flag(params, 'gosound'),
    useClips: params.get('clips') === null || flag(params, 'clips'),
    startMotion: startMotion(params.get('motion')),
    startEyes: startEyes(params.get('eyes')),
  };
}
