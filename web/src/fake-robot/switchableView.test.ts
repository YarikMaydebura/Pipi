import type { EyeState } from '@pipi/shared';
import { describe, expect, it, vi } from 'vitest';
import type { BaseLoop } from './motionPlan';
import { SwitchableView, type DisposableView } from './switchableView';

function fakeView() {
  return {
    setEyes: vi.fn((_s: EyeState) => undefined),
    setSpeechLevel: vi.fn(),
    setBase: vi.fn((_l: BaseLoop, _i: boolean) => undefined),
    perform: vi.fn(() => ({ finished: Promise.resolve() })),
    dispose: vi.fn(),
  } satisfies DisposableView;
}

describe('SwitchableView', () => {
  it('forwards to the current view and replays eyes + resting loop on a swap', () => {
    const first = fakeView();
    const view = new SwitchableView(first);
    view.setEyes('happy');
    view.setEyes('blink'); // one-shot: not replayed
    view.setBase('listen', false);
    expect(view.perform('nod')).not.toBeNull();
    const second = fakeView();
    view.replace(second);
    expect(first.dispose).toHaveBeenCalled();
    expect(second.setEyes).toHaveBeenCalledWith('happy');
    expect(second.setBase).toHaveBeenCalledWith('listen', true);
    view.setSpeechLevel(0.5);
    expect(second.setSpeechLevel).toHaveBeenCalledWith(0.5);
  });
});
