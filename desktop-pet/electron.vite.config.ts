import { defineConfig } from 'electron-vite';

// Default entries: src/main/index.ts, src/preload/index.ts, src/renderer/index.html.
export default defineConfig({
  main: {},
  preload: {
    // Sandboxed preload scripts cannot be ES modules, so build this one as CommonJS.
    build: { rolldownOptions: { output: { format: 'cjs' } } },
  },
  renderer: {
    // pipi.glb is imported with `?inline` (a data: URL), because fetch() of file:// URLs is
    // blocked in the packaged app. Listing .glb as an asset type makes `?inline` apply to it.
    assetsInclude: ['**/*.glb'],
  },
});
