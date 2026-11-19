// Showcase mode (`npm run showcase`): a bigger Pipi in the middle of the main screen that plays
// every animation in a loop, without the brain. For presentations; never used in the study.

export const SHOWCASE_FLAG = '--showcase';
const SHOWCASE_ENV = 'PIPI_SHOWCASE';
/** Added to the page URL; the renderer reads it (src/renderer/showcase/showcase.ts). */
export const SHOWCASE_SEARCH = 'showcase=1';

export function showcaseRequested(
  argv: readonly string[],
  env: Readonly<Record<string, string | undefined>>,
): boolean {
  return argv.includes(SHOWCASE_FLAG) || env[SHOWCASE_ENV] === '1';
}
