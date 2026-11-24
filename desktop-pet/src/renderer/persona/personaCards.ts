// Persona cards: three small cards under Pipi at the start of a session ("You can click one or
// just tell me!"). The brain shows them with `persona_picker` and hides them with an empty
// list; a click goes back as `user_click` with target "persona:<id>" (docs/INTERACTION_FLOW.md
// PERSONA_PICK). Text is set with textContent only.
//
// The window is click-through: it only catches the mouse where something clickable is under
// the cursor, so the cards report their own hit area (`hitTest`) next to Pipi's.
import { PERSONA_CLICK_PREFIX, type PersonaOption } from '@pipi/shared';
import type { ScreenPoint } from '../motion/idle';

/** How long the chosen card stays highlighted before the cards fade out. */
const CHOSEN_HOLD_MS = 650;

export interface Rect {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
}

export interface PersonaCards {
  show(options: readonly PersonaOption[]): void;
  hide(): void;
  /** True while the cursor is over a visible card (window coordinates). */
  hitTest(point: ScreenPoint): boolean;
}

export function pointInRects(point: ScreenPoint, rects: readonly Rect[]): boolean {
  return rects.some(
    (r) => point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom,
  );
}

/** The `user_click.target` of a card. */
export function cardTarget(id: string): string {
  return `${PERSONA_CLICK_PREFIX}${id}`;
}

function cardButton(option: PersonaOption, index: number): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'persona-card';
  button.dataset.persona = option.id;
  button.style.setProperty('--card-index', String(index));
  const label = document.createElement('span');
  label.className = 'persona-card-label';
  label.textContent = option.label;
  const description = document.createElement('span');
  description.className = 'persona-card-description';
  description.textContent = option.description;
  button.append(label, description);
  return button;
}

export function createPersonaCards(root: HTMLElement, onPick: (id: string) => void): PersonaCards {
  let hideTimer: ReturnType<typeof setTimeout> | undefined;

  const clearTimer = (): void => {
    if (hideTimer !== undefined) clearTimeout(hideTimer);
    hideTimer = undefined;
  };

  const hideNow = (): void => {
    clearTimer();
    root.dataset.visible = 'false';
    root.hidden = true;
    root.replaceChildren();
  };

  // The brain hides the cards the moment the click arrives: a chosen card still finishes its
  // short highlight first, so the participant sees what they picked.
  const hide = (): void => {
    if (root.dataset.chosen && hideTimer !== undefined) return;
    hideNow();
  };

  const pick = (button: HTMLButtonElement): void => {
    const id = button.dataset.persona;
    if (!id || root.dataset.chosen) return;
    root.dataset.chosen = id;
    button.dataset.chosen = 'true';
    onPick(id);
    hideTimer = setTimeout(hideNow, CHOSEN_HOLD_MS);
  };

  root.addEventListener('click', (event) => {
    const button = (event.target as Element | null)?.closest<HTMLButtonElement>('.persona-card');
    if (button) pick(button);
  });

  return {
    show(options) {
      if (options.length === 0) {
        hide();
        return;
      }
      clearTimer();
      delete root.dataset.chosen;
      root.replaceChildren(...options.map(cardButton));
      root.hidden = false;
      // Next frame, so the entrance transition runs from the hidden state.
      requestAnimationFrame(() => {
        root.dataset.visible = 'true';
      });
    },
    hide,
    hitTest(point) {
      if (root.hidden) return false;
      const cards = Array.from(root.querySelectorAll<HTMLElement>('.persona-card'));
      return pointInRects(
        point,
        cards.map((card) => card.getBoundingClientRect()),
      );
    },
  };
}
