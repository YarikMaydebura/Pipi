import { describe, expect, it } from 'vitest';
import { cardTarget, pointInRects } from './personaCards';

const CARD = { left: 10, top: 300, right: 100, bottom: 360 };

describe('persona cards hit test', () => {
  it('catches the cursor on a card, so the click-through window takes the click', () => {
    expect(pointInRects({ x: 50, y: 330 }, [CARD])).toBe(true);
    expect(pointInRects({ x: 10, y: 300 }, [CARD])).toBe(true); // the edge counts
  });

  it('lets clicks through everywhere else', () => {
    expect(pointInRects({ x: 5, y: 330 }, [CARD])).toBe(false);
    expect(pointInRects({ x: 50, y: 361 }, [CARD])).toBe(false);
    expect(pointInRects({ x: 50, y: 330 }, [])).toBe(false);
  });
});

describe('persona card click target', () => {
  it('is what the brain expects in user_click', () => {
    expect(cardTarget('calm')).toBe('persona:calm');
  });
});
