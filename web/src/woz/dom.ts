// Minimal DOM helpers. Server text only ever goes in via textContent, never as HTML.

export interface ElementOptions {
  readonly className?: string;
  readonly text?: string;
  readonly attrs?: Readonly<Record<string, string>>;
}

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  options: ElementOptions = {},
  children: readonly (Node | null)[] = [],
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = options.text;
  for (const [name, value] of Object.entries(options.attrs ?? {}))
    element.setAttribute(name, value);
  for (const child of children) if (child) element.append(child);
  return element;
}

/** Find a required element by id; a missing one is a bug in index.html, so fail loudly. */
export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`#${id} is missing from the WoZ page`);
  return element as T;
}

export function setText(element: HTMLElement, text: string): void {
  if (element.textContent !== text) element.textContent = text;
}
