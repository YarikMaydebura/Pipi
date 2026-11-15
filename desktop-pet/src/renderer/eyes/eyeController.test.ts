import { describe, expect, it } from 'vitest';
import { EyeController } from './eyeController';

const NO_GAZE = { x: 0, y: 0 };
const fixedRandom = (): number => 0.5; // never a double blink, gaps of 4.5 s

describe('EyeController', () => {
  it('starts idle and shows the requested state', () => {
    const eyes = new EyeController(0, fixedRandom);
    expect(eyes.visibleState(0)).toBe('idle');
    eyes.setState('listening', 1);
    expect(eyes.visibleState(1)).toBe('listening');
    expect(eyes.frame(1, NO_GAZE).state).toBe('listening');
  });

  it('treats blink as a one-shot that keeps the current state', () => {
    const eyes = new EyeController(0, fixedRandom);
    eyes.setState('thinking', 0);
    eyes.setState('blink', 1);
    expect(eyes.requestedState()).toBe('thinking');
    expect(eyes.frame(1.06, NO_GAZE).openness).toBeLessThan(0.5);
    expect(eyes.frame(1.5, NO_GAZE).openness).toBe(1);
  });

  it('blinks automatically after 3–6 seconds', () => {
    const eyes = new EyeController(0, fixedRandom);
    expect(eyes.frame(1, NO_GAZE).openness).toBe(1);
    expect(eyes.frame(4.5, NO_GAZE).openness).toBe(1); // blink starts now
    expect(eyes.frame(4.56, NO_GAZE).openness).toBeLessThan(0.2);
  });

  it('does not auto-blink when disabled or in non-blinking states', () => {
    const eyes = new EyeController(0, fixedRandom);
    eyes.frame(4.5, NO_GAZE);
    expect(eyes.frame(4.56, NO_GAZE, false).openness).toBe(1);
    eyes.setState('countdown', 5);
    eyes.frame(9, NO_GAZE);
    expect(eyes.frame(9.06, NO_GAZE).openness).toBe(1);
  });

  it('flashes a temporary state and then returns', () => {
    const eyes = new EyeController(0, fixedRandom);
    eyes.setState('sleepy', 0);
    eyes.flash('happy', 1, 1.2);
    expect(eyes.visibleState(1.5)).toBe('happy');
    expect(eyes.visibleState(2.5)).toBe('sleepy');
  });
});
