// The speech bubble above Pipi's head (subtitles). Text is set with textContent only, never as
// HTML. Looks and the pop-in animation live in style.css (.speech-bubble).

export interface CaptionView {
  show(text: string): void;
  hide(): void;
}

export function createSpeechBubble(root: HTMLElement): CaptionView {
  const text = root.querySelector<HTMLElement>('.speech-bubble-text') ?? root;
  return {
    show(value) {
      text.textContent = value;
      root.dataset['visible'] = 'true';
      root.setAttribute('aria-hidden', 'false');
    },
    hide() {
      root.dataset['visible'] = 'false';
      root.setAttribute('aria-hidden', 'true');
    },
  };
}
