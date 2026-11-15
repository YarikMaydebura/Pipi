import { describe, expect, it } from 'vitest';
import { GRIN_MOTIONS, GRIN_S, MouthController } from './mouthController';

describe('MouthController', () => {
  it('follows the eye state', () => {
    const mouth = new MouthController();
    expect(mouth.frame('idle', 0, 0).shape).toBe('smile');
    expect(mouth.frame('surprised', 0, 0).shape).toBe('small_o');
  });

  it('grins for a moment after a happy motion, then goes back', () => {
    const mouth = new MouthController();
    mouth.onMotion('celebrate', 10);
    expect(mouth.frame('idle', 0, 10.5).shape).toBe('big_smile');
    expect(mouth.frame('idle', 0, 10 + GRIN_S + 0.01).shape).toBe('smile');
    mouth.onMotion('nod', 20);
    expect(mouth.frame('idle', 0, 20.1).shape).toBe('smile');
    expect(GRIN_MOTIONS).toContain('celebrate');
  });

  it('does not grin on a dark screen', () => {
    const mouth = new MouthController();
    mouth.onMotion('celebrate', 0);
    expect(mouth.frame('off', 0, 0.1).shape).toBe('off');
  });

  it('lets the debug override win until it is cleared', () => {
    const mouth = new MouthController();
    mouth.setOverride('wavy');
    expect(mouth.frame('happy', 0, 0).shape).toBe('wavy');
    mouth.setOverride(null);
    expect(mouth.frame('happy', 0, 0).shape).toBe('big_smile');
  });
});

describe('MouthController flash', () => {
  it('shows a reaction mouth until it ends, over the grin but under the debug override', () => {
    const mouth = new MouthController();
    mouth.onMotion('celebrate', 0); // grin
    mouth.flash('small_o', 1);
    expect(mouth.frame('idle', 0, 0.5).shape).toBe('small_o');
    expect(mouth.frame('idle', 0, 1.2).shape).toBe('big_smile'); // flash over, grin left
    mouth.setOverride('wavy');
    mouth.flash('small_o', 5);
    expect(mouth.frame('idle', 0, 2).shape).toBe('wavy');
  });

  it('is cleared by flash(null) and never lights a switched-off face', () => {
    const mouth = new MouthController();
    mouth.flash('small_o', 10);
    expect(mouth.frame('off', 0, 1).shape).toBe('off');
    mouth.flash(null, 0);
    expect(mouth.frame('idle', 0, 1).shape).toBe('smile');
  });
});
