import { defineConfig } from 'electron-vite';

// Default entries: src/main/index.ts, src/preload/index.ts, src/renderer/index.html.
export default defineConfig({
  main: {},
  preload: {
    // Sandboxed preload scripts cannot be ES modules, so build this one as CommonJS.
    build: { rolldownOptions: { output: { format: 'cjs' } } },
  },
  renderer: {},
});
