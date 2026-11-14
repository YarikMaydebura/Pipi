/** Write a short status line into the page's #status element (textContent, never HTML). */
export function showStatus(text: string): void {
  const el = document.querySelector<HTMLElement>('#status');
  if (el) el.textContent = text;
}
