import { resolve } from 'node:path';
import { defineConfig } from 'vite';

const root = import.meta.dirname;

// `npm run dev`: the WoZ panel's socket (/ws/woz) is proxied to a running brain, so the panel
// code is the same in dev and when the brain serves the built page. Port = woz.port in config.
const wozPort = process.env.PIPI_WOZ_PORT ?? '8766';

// Two pages: /woz/ (experimenter panel) and /fake-robot/ (browser robot body).
export default defineConfig({
  server: {
    proxy: {
      '/ws/woz': { target: `ws://127.0.0.1:${wozPort}`, ws: true },
    },
  },
  build: {
    rolldownOptions: {
      input: {
        index: resolve(root, 'index.html'),
        woz: resolve(root, 'woz/index.html'),
        fakeRobot: resolve(root, 'fake-robot/index.html'),
      },
    },
  },
});
