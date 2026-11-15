// Test helper: a fake 2D canvas context that records method calls and the colours used, so the
// pure drawers (eyes, mouth) can be tested without a real canvas.

export interface Call {
  readonly name: string;
  readonly args: readonly unknown[];
}

export interface CanvasRecorder<T> {
  readonly ctx: T;
  readonly calls: Call[];
  readonly colors: Set<string>;
  /** Last value assigned to a property such as lineWidth or shadowBlur. */
  readonly state: Record<string, unknown>;
}

const METHODS = [
  'save',
  'restore',
  'beginPath',
  'closePath',
  'arc',
  'ellipse',
  'roundRect',
  'moveTo',
  'lineTo',
  'fill',
  'stroke',
  'clip',
  'clearRect',
];

export function canvasRecorder<T>(): CanvasRecorder<T> {
  const calls: Call[] = [];
  const colors = new Set<string>();
  const gradient = {
    addColorStop: (_offset: number, color: string) => colors.add(color),
  };
  const state: Record<string, unknown> = {};
  const target: Record<string, unknown> = {
    createLinearGradient: (...args: unknown[]) => {
      calls.push({ name: 'createLinearGradient', args });
      return gradient;
    },
  };
  for (const name of METHODS) {
    target[name] = (...args: unknown[]) => calls.push({ name, args });
  }
  const ctx = new Proxy(target, {
    set(_t, key: string, value: unknown) {
      state[key] = value;
      if ((key === 'fillStyle' || key === 'strokeStyle') && typeof value === 'string') {
        colors.add(value);
      }
      return true;
    },
    get(t, key: string) {
      return key in t ? t[key] : state[key];
    },
  }) as unknown as T;
  return { ctx, calls, colors, state };
}

/** Names of the recorded calls, in order. */
export function callNames(calls: readonly Call[]): string[] {
  return calls.map((c) => c.name);
}
