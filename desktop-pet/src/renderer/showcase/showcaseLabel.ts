// The title under Pipi in showcase mode: what is playing now and how far through the show.
import type { ShowcaseStep } from './playlist';

export const SHOWCASE_BODY_CLASS = 'is-showcase';

/** Returns the function that shows a step's title (text only, never HTML). */
export function createShowcaseLabel(
  label: HTMLElement,
): (step: ShowcaseStep, index: number, total: number) => void {
  const title = document.createElement('span');
  title.className = 'showcase-label-title';
  const count = document.createElement('span');
  count.className = 'showcase-label-count';
  label.replaceChildren(title, count);
  label.hidden = false;
  document.body.classList.add(SHOWCASE_BODY_CLASS);
  return (step, index, total) => {
    title.textContent = step.title;
    count.textContent = `${index + 1} / ${total}`;
  };
}
