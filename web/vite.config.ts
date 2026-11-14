import { resolve } from 'node:path';
import { defineConfig } from 'vite';

const root = import.meta.dirname;

// Two pages: /woz/ (experimenter panel) and /fake-robot/ (browser robot body).
export default defineConfig({
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
