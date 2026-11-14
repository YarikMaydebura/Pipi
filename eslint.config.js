// One ESLint config for all TypeScript in the repo (shared/, desktop-pet/, web/).
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**',
      '**/out/**',
      '**/dist/**',
      '**/coverage/**',
      'brain/**',
      'docs/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-console': ['warn', { allow: ['warn', 'error', 'info'] }],
    },
  },
  {
    // Electron main/preload and config files run in Node.
    files: ['desktop-pet/src/main/**', 'desktop-pet/src/preload/**', '**/*.config.{js,ts}'],
    languageOptions: { globals: globals.node },
  },
  {
    // Renderer and web pages run in the browser.
    files: ['desktop-pet/src/renderer/**', 'web/src/**'],
    languageOptions: { globals: globals.browser },
  },
);
